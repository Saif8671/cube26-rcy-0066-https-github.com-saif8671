"""Normalizers for converting raw external records to internal model structures."""

from typing import Any, Dict, Optional

from app.ingestion.validators import (
    validate_charge_record,
    validate_reimbursement_record,
    validate_evidence_record,
)

# Common field alias mapping for charges
CHARGE_FIELD_ALIASES = {
    "line_id": "charge_id",
    "fee_id": "charge_id",
    "fee_type": "charge_type",
    "fee_amount": "amount",
    "amount_usd": "amount",
    "transaction_amount": "amount",
    "fee_date": "charge_date",
    "posted_date": "charge_date",
    "date": "charge_date",
    "transaction_date": "charge_date",
    "shipmentid": "shipment_id",
    "fba_shipment_id": "shipment_id",
    "orderid": "order_id",
}

# Common field alias mapping for reimbursements
REIMBURSEMENT_FIELD_ALIASES = {
    "refund_id": "reimbursement_id",
    "credit_id": "reimbursement_id",
    "payout_id": "reimbursement_id",
    "refund_amount": "amount",
    "credit_amount": "amount",
    "date": "reimbursement_date",
    "refund_date": "reimbursement_date",
    "original_charge_id": "charge_id",
    "fee_id": "charge_id",
}

# Common field alias mapping for generic evidence
EVIDENCE_FIELD_ALIASES = {
    "record_id": "evidence_id",
    "proof_id": "evidence_id",
    "audit_id": "evidence_id",
    "manager": "source_manager",
    "department": "source_manager",
    "proof_type": "evidence_type",
    "type": "evidence_type",
    "content": "evidence_content",
    "payload": "evidence_content",
    "data": "evidence_content",
    "timestamp": "evidence_timestamp",
    "captured_at": "evidence_timestamp",
    "date": "evidence_timestamp",
    "shipmentid": "shipment_id",
    "fba_shipment_id": "shipment_id",
    "orderid": "order_id",
}


def _apply_aliases(raw: Dict[str, Any], alias_map: Dict[str, str]) -> Dict[str, Any]:
    """Map known alias keys into canonical schema field names without losing unknown keys."""
    normalized: Dict[str, Any] = {}
    for key, val in raw.items():
        if key is None:
            continue
        clean_key = str(key).strip().lower()
        target_key = alias_map.get(clean_key, clean_key)
        normalized[target_key] = val
    return normalized


def normalize_charge(
    raw_record: Dict[str, Any],
    source_report: Optional[str] = None,
    row_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Normalize raw charge dictionary into validated schema fields.
    Preserves raw dictionary in raw_data.
    """
    mapped = _apply_aliases(raw_record, CHARGE_FIELD_ALIASES)
    if source_report and not mapped.get("source_report"):
        mapped["source_report"] = source_report

    # Save original raw data if not explicitly passed
    if "raw_data" not in mapped:
        mapped["raw_data"] = dict(raw_record)

    return validate_charge_record(mapped, row_index=row_index)


def normalize_reimbursement(
    raw_record: Dict[str, Any],
    source_report: Optional[str] = None,
    row_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Normalize raw reimbursement dictionary into validated schema fields.
    Preserves raw dictionary in raw_data.
    """
    mapped = _apply_aliases(raw_record, REIMBURSEMENT_FIELD_ALIASES)
    if "raw_data" not in mapped:
        mapped["raw_data"] = dict(raw_record)

    return validate_reimbursement_record(mapped, row_index=row_index)


# ==============================================================================
# Manager 1: RECEIVING EVIDENCE NORMALIZER
# Columns: record_id, unit_id, org_id, po_number, po_line, supplier, sku, asin,
# product_title, spec_colour, spec_variant, spec_components, cartons_ordered,
# cartons_received, units_per_carton_ordered, units_per_carton_counted,
# qty_ordered, qty_received, identity_match, carton_damage, unit_damage,
# quality_flags, photo_refs, operator_id, captured_at
# ==============================================================================
def normalize_receiving_evidence(
    raw_record: Dict[str, Any],
    source_report: Optional[str] = None,
    row_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Parse real Receiving manager CSV columns into structured evidence record."""
    evidence_id = raw_record.get("record_id") or raw_record.get("evidence_id")
    unit_id = raw_record.get("unit_id")
    org_id = raw_record.get("org_id")
    sku = raw_record.get("sku")
    asin = raw_record.get("asin")
    captured_at = raw_record.get("captured_at") or raw_record.get("evidence_timestamp")

    content = {
        "record_id": raw_record.get("record_id"),
        "unit_id": unit_id,
        "org_id": org_id,
        "po_number": raw_record.get("po_number"),
        "po_line": raw_record.get("po_line"),
        "supplier": raw_record.get("supplier"),
        "sku": sku,
        "asin": asin,
        "product_title": raw_record.get("product_title"),
        "spec_colour": raw_record.get("spec_colour"),
        "spec_variant": raw_record.get("spec_variant"),
        "spec_components": raw_record.get("spec_components"),
        "cartons_ordered": raw_record.get("cartons_ordered"),
        "cartons_received": raw_record.get("cartons_received"),
        "units_per_carton_ordered": raw_record.get("units_per_carton_ordered"),
        "units_per_carton_counted": raw_record.get("units_per_carton_counted"),
        "qty_ordered": raw_record.get("qty_ordered"),
        "qty_received": raw_record.get("qty_received"),
        "identity_match": raw_record.get("identity_match"),
        "carton_damage": raw_record.get("carton_damage"),
        "unit_damage": raw_record.get("unit_damage"),
        "quality_flags": raw_record.get("quality_flags"),
        "photo_refs": raw_record.get("photo_refs"),
        "operator_id": raw_record.get("operator_id"),
        "captured_at": captured_at,
    }

    record = {
        "evidence_id": evidence_id,
        "source_manager": "Receiving",
        "evidence_type": "receiving_inspection",
        "evidence_content": content,
        "evidence_timestamp": captured_at,
        "org_id": org_id,
        "unit_id": unit_id,
        "sku": sku,
        "asin": asin,
    }
    return validate_evidence_record(record, row_index=row_index)


# ==============================================================================
# Manager 2: PREP EVIDENCE NORMALIZER
# Columns: record_id, unit_id, org_id, work_order_id, fba_shipment_id, sku, asin,
# fnsku, prep_price_usd, wo_polybag, wo_suffocation_warning, wo_expiry_date,
# wo_handling_marks, polybag_present_sealed, suffocation_warning,
# fnsku_label_placement, original_barcode_covered, expiry_date, handling_marks,
# photo_refs, operator_id, captured_at
# ==============================================================================
def normalize_prep_evidence(
    raw_record: Dict[str, Any],
    source_report: Optional[str] = None,
    row_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Parse real Prep manager CSV columns into structured evidence record.
    Explicitly preserves requirement flags vs observed values pairing.
    """
    evidence_id = raw_record.get("record_id") or raw_record.get("evidence_id")
    unit_id = raw_record.get("unit_id")
    org_id = raw_record.get("org_id")
    sku = raw_record.get("sku")
    asin = raw_record.get("asin")
    fnsku = raw_record.get("fnsku")
    fba_shipment_id = raw_record.get("fba_shipment_id") or raw_record.get("shipment_id")
    captured_at = raw_record.get("captured_at") or raw_record.get("evidence_timestamp")

    content = {
        "record_id": raw_record.get("record_id"),
        "unit_id": unit_id,
        "org_id": org_id,
        "work_order_id": raw_record.get("work_order_id"),
        "fba_shipment_id": fba_shipment_id,
        "sku": sku,
        "asin": asin,
        "fnsku": fnsku,
        "prep_price_usd": raw_record.get("prep_price_usd"),
        "requirements": {
            "wo_polybag": raw_record.get("wo_polybag"),
            "wo_suffocation_warning": raw_record.get("wo_suffocation_warning"),
            "wo_expiry_date": raw_record.get("wo_expiry_date"),
            "wo_handling_marks": raw_record.get("wo_handling_marks"),
        },
        "observed": {
            "polybag_present_sealed": raw_record.get("polybag_present_sealed"),
            "suffocation_warning": raw_record.get("suffocation_warning"),
            "fnsku_label_placement": raw_record.get("fnsku_label_placement"),
            "original_barcode_covered": raw_record.get("original_barcode_covered"),
            "expiry_date": raw_record.get("expiry_date"),
            "handling_marks": raw_record.get("handling_marks"),
        },
        "wo_polybag": raw_record.get("wo_polybag"),
        "wo_suffocation_warning": raw_record.get("wo_suffocation_warning"),
        "wo_expiry_date": raw_record.get("wo_expiry_date"),
        "wo_handling_marks": raw_record.get("wo_handling_marks"),
        "polybag_present_sealed": raw_record.get("polybag_present_sealed"),
        "suffocation_warning": raw_record.get("suffocation_warning"),
        "fnsku_label_placement": raw_record.get("fnsku_label_placement"),
        "original_barcode_covered": raw_record.get("original_barcode_covered"),
        "expiry_date": raw_record.get("expiry_date"),
        "handling_marks": raw_record.get("handling_marks"),
        "photo_refs": raw_record.get("photo_refs"),
        "operator_id": raw_record.get("operator_id"),
        "captured_at": captured_at,
    }

    record = {
        "evidence_id": evidence_id,
        "source_manager": "Prep",
        "evidence_type": "prep_inspection",
        "evidence_content": content,
        "evidence_timestamp": captured_at,
        "org_id": org_id,
        "unit_id": unit_id,
        "fnsku": fnsku,
        "sku": sku,
        "asin": asin,
        "shipment_id": fba_shipment_id,
    }
    return validate_evidence_record(record, row_index=row_index)


# ==============================================================================
# Manager 3: PACK EVIDENCE NORMALIZER
# Columns: record_id, unit_id, org_id, order_id, channel, order_lines,
# observed_in_box, operator_verdict, photo_refs, operator_id, captured_at
# ==============================================================================
def normalize_pack_evidence(
    raw_record: Dict[str, Any],
    source_report: Optional[str] = None,
    row_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Parse real Pack manager CSV columns into structured evidence record."""
    evidence_id = raw_record.get("record_id") or raw_record.get("evidence_id")
    unit_id = raw_record.get("unit_id")
    org_id = raw_record.get("org_id")
    order_id = raw_record.get("order_id")
    captured_at = raw_record.get("captured_at") or raw_record.get("evidence_timestamp")

    content = {
        "record_id": raw_record.get("record_id"),
        "unit_id": unit_id,
        "org_id": org_id,
        "order_id": order_id,
        "channel": raw_record.get("channel"),
        "order_lines": raw_record.get("order_lines"),
        "observed_in_box": raw_record.get("observed_in_box"),
        "operator_verdict": raw_record.get("operator_verdict"),
        "photo_refs": raw_record.get("photo_refs"),
        "operator_id": raw_record.get("operator_id"),
        "captured_at": captured_at,
    }

    record = {
        "evidence_id": evidence_id,
        "source_manager": "Pack",
        "evidence_type": "pack_verification",
        "evidence_content": content,
        "evidence_timestamp": captured_at,
        "org_id": org_id,
        "unit_id": unit_id,
        "order_id": order_id,
    }
    return validate_evidence_record(record, row_index=row_index)


# ==============================================================================
# Manager 4: RETURNS EVIDENCE NORMALIZER
# Columns: record_id, unit_id, org_id, order_id, ordered_sku, ordered_asin,
# identity_match, parts_list, parts_missing, observed_state, amazon_condition,
# operator_disposition, photo_refs, operator_id, captured_at
# ==============================================================================
def normalize_returns_evidence(
    raw_record: Dict[str, Any],
    source_report: Optional[str] = None,
    row_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Parse real Returns manager CSV columns into structured evidence record."""
    evidence_id = raw_record.get("record_id") or raw_record.get("evidence_id")
    unit_id = raw_record.get("unit_id")
    org_id = raw_record.get("org_id")
    order_id = raw_record.get("order_id")
    sku = raw_record.get("ordered_sku") or raw_record.get("sku")
    asin = raw_record.get("ordered_asin") or raw_record.get("asin")
    captured_at = raw_record.get("captured_at") or raw_record.get("evidence_timestamp")

    content = {
        "record_id": raw_record.get("record_id"),
        "unit_id": unit_id,
        "org_id": org_id,
        "order_id": order_id,
        "ordered_sku": raw_record.get("ordered_sku"),
        "ordered_asin": raw_record.get("ordered_asin"),
        "identity_match": raw_record.get("identity_match"),
        "parts_list": raw_record.get("parts_list"),
        "parts_missing": raw_record.get("parts_missing"),
        "observed_state": raw_record.get("observed_state"),
        "amazon_condition": raw_record.get("amazon_condition"),
        "operator_disposition": raw_record.get("operator_disposition"),
        "photo_refs": raw_record.get("photo_refs"),
        "operator_id": raw_record.get("operator_id"),
        "captured_at": captured_at,
    }

    record = {
        "evidence_id": evidence_id,
        "source_manager": "Returns",
        "evidence_type": "return_evaluation",
        "evidence_content": content,
        "evidence_timestamp": captured_at,
        "org_id": org_id,
        "unit_id": unit_id,
        "sku": sku,
        "asin": asin,
        "order_id": order_id,
    }
    return validate_evidence_record(record, row_index=row_index)


def normalize_evidence(
    raw_record: Dict[str, Any],
    source_report: Optional[str] = None,
    row_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Normalize raw evidence dictionary into validated schema fields.
    Automatically detects which of the 4 manager pods generated the record,
    or falls back to generic evidence parsing.
    """
    keys = {str(k).strip().lower() for k in raw_record.keys() if k is not None}

    # Manager pod detection by signature columns
    if "po_number" in keys or "po_line" in keys or "cartons_ordered" in keys:
        return normalize_receiving_evidence(raw_record, source_report=source_report, row_index=row_index)
    elif "wo_polybag" in keys or "work_order_id" in keys or "prep_price_usd" in keys:
        return normalize_prep_evidence(raw_record, source_report=source_report, row_index=row_index)
    elif "observed_in_box" in keys or "operator_verdict" in keys or "order_lines" in keys:
        return normalize_pack_evidence(raw_record, source_report=source_report, row_index=row_index)
    elif "ordered_sku" in keys or "operator_disposition" in keys or "parts_list" in keys:
        return normalize_returns_evidence(raw_record, source_report=source_report, row_index=row_index)

    # Generic evidence fallback
    mapped = _apply_aliases(raw_record, EVIDENCE_FIELD_ALIASES)
    return validate_evidence_record(mapped, row_index=row_index)
