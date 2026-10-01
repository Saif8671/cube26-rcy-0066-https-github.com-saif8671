"""Deterministic, evidence-first recovery preview/run rules."""
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import current_org
from app.models.assessment_log import AssessmentLog
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.models.evidence import Evidence
from app.models.pipeline_error import PipelineError
from app.models.reimbursement import Reimbursement
from app.core.logging import logger

RELEVANCE = {
    "inbound_defect_fee": {"Prep": {"polybag_present_sealed", "suffocation_warning", "fnsku_label_placement", "original_barcode_covered", "expiry_date", "handling_marks"}, "Receiving": {"carton_damage", "unit_damage", "quality_flags"}},
    "lost_inbound": {"Receiving": {"qty_ordered", "qty_received", "cartons_expected", "cartons_received", "identity_match"}},
    "refund_issued_item_not_returned": {"Returns": {"identity_match", "parts_missing", "observed_state", "operator_disposition"}},
    "damaged_in_warehouse": {"Returns": {"identity_match", "parts_missing", "observed_state", "operator_disposition"}},
    "fulfilment_fee_weight_tier": {},
}

# Controlled handbook/fixture vocabulary. Anything absent from these sets is UNCLEAR.
VALUE_RULES = {
    "carton_damage": ({"none"}, {"crushing", "tears", "water", "damaged"}),
    "unit_damage": ({"none"}, {"crushing", "tears", "water", "damaged"}),
    "quality_flags": ({"", "none"}, {"missing_components", "wrong_colour", "obvious_defect"}),
    "polybag_present_sealed": ({"yes", "true", "not_required"}, {"no", "false", "not_sealed"}),
    "suffocation_warning": ({"yes", "true", "not_required"}, {"no", "false"}),
    "fnsku_label_placement": ({"legible", "flat", "on_curve", "on_edge", "on_seam", "not_required"}, {"missing", "illegible", "illegible_after_wrap"}),
    "original_barcode_covered": ({"yes", "true", "not_required"}, {"no", "false"}),
    "expiry_date": ({"legible", "not_required"}, {"missing", "illegible"}),
    "handling_marks": ({"all_present", "not_required"}, {"missing"}),
    "identity_match": ({"yes", "true"}, {"no", "false"}),
    "parts_missing": ({"", "none"}, set()),
    "observed_state": ({"factory_sealed", "opened_unused"}, {"damaged", "signs_of_use"}),
    "operator_disposition": ({"restock", "refurbish"}, {"liquidate", "dispose"}),
}

def _text(v: Any) -> str:
    return "" if v is None else str(v).strip().lower()

def _classification(field: str, value: Any) -> str:
    value = _text(value)
    if field == "quality_flags" and ";" in value:
        classifications = [_classification(field, part) for part in value.split(";")]
        if "DEFECT" in classifications:
            return "DEFECT"
        if classifications and all(item == "CLEAR" for item in classifications):
            return "CLEAR"
        return "UNCLEAR"
    clear, defect = VALUE_RULES.get(field, (set(), set()))
    if value in clear:
        return "CLEAR"
    if value in defect:
        return "DEFECT"
    return "UNCLEAR"

def _evidence_values(evidence, rules):
    return [(e, field, e.evidence_content.get(field)) for e in evidence for field in sorted(rules.get(e.source_manager, set())) if field in (e.evidence_content or {})]

def _inbound_decision(charge, evidence, values):
    if not values:
        return "SILENT", "RULE_INBOUND_NO_RELEVANT_EVIDENCE", "No relevant inbound evidence was retrieved for this unit.", None
    unclear = [(field, value) for _, field, value in values if _classification(field, value) == "UNCLEAR"]
    if unclear:
        detail = ", ".join(f"{field}={value!r}" for field, value in unclear)
        return "UNCERTAIN", "RULE_INBOUND_UNCLEAR_VALUE", f"UNCERTAIN because relevant value is unclear: {detail}.", None
    by_check = defaultdict(list)
    for e, field, value in values:
        by_check[(field, field)].append((e, _text(value)))
    disagreements = [(field, sorted({value for _, value in rows})) for (field, _), rows in by_check.items() if len({value for _, value in rows}) > 1]
    if disagreements:
        detail = "; ".join(f"{field}={vals}" for field, vals in disagreements)
        return "UNCERTAIN", "RULE_INBOUND_DISAGREEMENT", f"UNCERTAIN because records for the same org+unit+check disagree: {detail}.", None
    defects = [(e, field, value) for e, field, value in values if _classification(field, value) == "DEFECT"]
    if defects:
        detail = ", ".join(f"{field}={value!r}" for _, field, value in defects)
        return "SUPPORTED", "RULE_INBOUND_DOCUMENTED_DEFECT", f"Defect documented on inbound check(s): {detail}; no claim permitted.", None
    checks = "; ".join(f"{e.source_manager} {field}={value!r} (source Manager {e.source_manager}, evidence id {e.evidence_id}, captured_at {e.evidence_timestamp.isoformat()})" for e, field, value in values)
    return "CONTRADICTED", "RULE_INBOUND_ALL_CHECKS_CLEAR", f"No defect documented on any inbound check recorded for this unit. Checks: {checks}. The fee row does not name a specific defect, so human review is required.", None

def _returns_decision(values):
    if not values:
        return "SILENT", "RULE_RETURNS_NO_RELEVANT_EVIDENCE", "No relevant Returns evidence was retrieved for this unit."
    unclear = [(field, value) for _, field, value in values if _classification(field, value) == "UNCLEAR"]
    if unclear:
        return "UNCERTAIN", "RULE_RETURNS_UNCLEAR_VALUE", "UNCERTAIN because relevant Returns value is unclear: " + ", ".join(f"{f}={v!r}" for f, v in unclear) + "."
    defects = [(field, value) for _, field, value in values if _classification(field, value) == "DEFECT"]
    if defects:
        return "SUPPORTED", "RULE_RETURNS_DOCUMENTED_DEFECT", "Returns evidence documents: " + ", ".join(f"{f}={v!r}" for f, v in defects) + "; no claim permitted."
    return "CONTRADICTED", "RULE_RETURNS_ALL_CHECKS_CLEAR", "All retrieved Returns checks are CLEAR; the fee is contradicted."

def evaluate_charge(db: Session, charge: Charge, *, persist: bool = True) -> dict:
    existing_reimbursement = db.scalar(select(Reimbursement).where(Reimbursement.org_id == charge.org_id, Reimbursement.charge_id == charge.id))
    duplicate = db.scalar(select(Charge).where(
        Charge.org_id == charge.org_id,
        Charge.unit_id == charge.unit_id,
        Charge.charge_type == charge.charge_type,
        Charge.amount == charge.amount,
        Charge.charge_date == charge.charge_date,
        Charge.charge_id != charge.charge_id,
    )) if charge.unit_id else None
    if existing_reimbursement:
        assessment, rule_code, reason, status = "SILENT", "RULE_ALREADY_REIMBURSED", f"Reimbursement {existing_reimbursement.reimbursement_id} is already linked; no claim permitted.", "ALREADY_REIMBURSED"
    elif duplicate:
        assessment, rule_code, reason, status = "SILENT", "RULE_DUPLICATE", f"Duplicate of charge {duplicate.charge_id} under the same org, unit, charge type, amount, and posted date; no claim permitted.", "DUPLICATE"
    else:
        assessment = rule_code = reason = status = None
    rules = RELEVANCE.get(charge.charge_type, {})
    evidence = [] if assessment is not None else (list(db.scalars(select(Evidence).where(Evidence.org_id == charge.org_id, Evidence.data_origin == "judge_data", Evidence.unit_id == charge.unit_id)).all()) if charge.unit_id else [])
    usable = [e for e in evidence if set((e.evidence_content or {}).keys()) & rules.get(e.source_manager, set())]
    values = _evidence_values(usable, rules)
    if assessment is not None:
        pass
    elif charge.amount == 0 or charge.report_type == "inventory_adjustment":
        assessment, rule_code, reason, status = "SILENT", "RULE_ZERO_OR_INVENTORY", "Zero-value or inventory-adjustment charge; no claim permitted.", None
    elif charge.charge_type == "inbound_defect_fee":
        assessment, rule_code, reason, status = _inbound_decision(charge, usable, values)
    elif charge.charge_type in {"refund_issued_item_not_returned", "damaged_in_warehouse"}:
        assessment, rule_code, reason = _returns_decision(values); status = None
    elif not rules or not usable:
        assessment, rule_code, reason, status = "SILENT", "RULE_NO_RELEVANT_EVIDENCE", "No configured relevant evidence was retrieved for this charge.", None
    else:
        assessment, rule_code, reason, status = "SILENT", "RULE_UNSUPPORTED_CHARGE_TYPE", "No deterministic rule is configured for this charge type.", None

    evidence_ids = [e.evidence_id for e in usable]
    claim = None
    if persist:
        log = db.scalar(select(AssessmentLog).where(AssessmentLog.org_id == charge.org_id, AssessmentLog.charge_id == charge.id).order_by(AssessmentLog.created_at.desc()))
        if log is None:
            db.add(AssessmentLog(org_id=charge.org_id, charge_id=charge.id, assessment=assessment, claim_supported=False, claim_amount=None, confidence=None, reason=reason, evidence_ids=evidence_ids))
        else:
            log.assessment, log.reason, log.evidence_ids = assessment, reason, evidence_ids
        claim = db.scalar(select(Claim).where(Claim.org_id == charge.org_id, Claim.charge_id == charge.id).order_by(Claim.created_at.desc()))
        if assessment == "CONTRADICTED" and claim is None and charge.data_origin == "judge_data" and charge.amount > 0:
            claim = Claim(claim_id=f"CLM-{str(charge.id)[:8].upper()}", org_id=charge.org_id, charge_id=charge.id, assessment=assessment, claim_amount=min(Decimal(charge.amount), Decimal(charge.amount)), confidence=Decimal("1.0000"), explanation=reason, status="READY_FOR_REVIEW", source_manager=usable[0].source_manager if usable else None, data_origin=charge.data_origin)
            db.add(claim); db.flush()
            for e in usable: db.add(ClaimEvidence(org_id=charge.org_id, claim_id=claim.id, evidence_id=e.id))
            charge.status = "PROCESSED"
    result = {"charge_id": charge.charge_id, "charge_type": charge.charge_type, "report_type": charge.report_type, "amount": charge.amount, "assessment": assessment, "rule": rule_code, "status": status or (claim.status if claim else None), "explanation": reason, "evidence_ids": evidence_ids, "claim_id": claim.claim_id if claim and assessment == "CONTRADICTED" and charge.data_origin == "judge_data" else None}
    if charge.charge_type in {"refund_issued_item_not_returned", "damaged_in_warehouse", "lost_inbound"}:
        rows = list(db.scalars(select(Evidence.evidence_id).where(Evidence.org_id == charge.org_id, Evidence.unit_id == charge.unit_id, Evidence.source_manager.in_(["Returns", "Receiving"]))).all()) if charge.unit_id else []
        result["returns_check"] = {"charge_id": charge.charge_id, "unit_id": charge.unit_id, "any_returns_or_receiving_row": bool(rows), "retrieved_evidence_ids": rows}
    return result

def _charges_for_org(db: Session):
    org = current_org(db)
    return org, list(db.scalars(select(Charge).where(Charge.org_id == org, Charge.data_origin == "judge_data").order_by(Charge.charge_date, Charge.charge_id)).all())

def _value_catalog(db, org):
    out = {}
    for manager, fields in {"Receiving": RELEVANCE["inbound_defect_fee"]["Receiving"], "Prep": RELEVANCE["inbound_defect_fee"]["Prep"], "Returns": RELEVANCE["refund_issued_item_not_returned"]["Returns"]}.items():
        for field in sorted(fields):
            vals = sorted({_text((e.evidence_content or {}).get(field)) for e in db.scalars(select(Evidence).where(Evidence.org_id == org, Evidence.source_manager == manager, Evidence.evidence_content.has_key(field))).all()})
            out[field] = {"values": [{"value": v, "classification": _classification(field, v)} for v in vals], "rule": "VALUE_RULES / Cube_Buildathon controlled vocabulary; unknown values are UNCLEAR"}
    return out

def preview_recovery(db: Session) -> dict:
    org, charges = _charges_for_org(db)
    results = [evaluate_charge(db, charge, persist=False) for charge in charges]
    return {"org_id": org, "total": len(results), "counts": dict(Counter(r["assessment"] for r in results)), "value_catalog": _value_catalog(db, org), "results": results, "persisted": False}

def run_recovery(db: Session) -> dict:
    org, charges = _charges_for_org(db); results = []
    for charge in charges:
        try:
            with db.begin_nested(): results.append(evaluate_charge(db, charge, persist=True)); db.flush()
        except Exception as exc:
            logger.exception("recovery charge failed charge_id=%s message=%s", charge.charge_id, str(exc)); db.rollback()
            results.append({"charge_id": charge.charge_id, "charge_type": charge.charge_type, "report_type": charge.report_type, "amount": charge.amount, "assessment": "ERROR", "rule": "RULE_EVALUATION_ERROR", "status": "pending", "explanation": "Charge could not be evaluated; see server logs."})
    db.commit(); return {"org_id": org, "total": len(results), "counts": dict(Counter(r["assessment"] for r in results)), "results": results, "persisted": True}
