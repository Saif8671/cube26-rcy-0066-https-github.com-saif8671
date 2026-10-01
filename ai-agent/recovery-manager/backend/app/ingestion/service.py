"""Ingestion service coordinating reading, validation, normalization, and persistence."""

from dataclasses import dataclass, field, asdict
from io import IOBase
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Set, Union

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, ProgrammingError, DBAPIError
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.core.database import current_org
from app.ingestion.exceptions import (
    DuplicateRecordError,
    IdentifierResolutionError,
    IngestionError,
    RecordValidationError,
)
from app.ingestion.normalizers import (
    normalize_charge,
    normalize_reimbursement,
    normalize_evidence,
)
from app.ingestion.readers import read_file
from app.models.charge import Charge
from app.models.evidence import Evidence
from app.models.order import Order
from app.models.reimbursement import Reimbursement
from app.models.shipment import Shipment


@dataclass
class IngestionErrorDetail:
    """Detailed information for an individual failed record."""
    row_index: Optional[int]
    identifier: Optional[str]
    error_code: str
    reason: str


def _reason_code(error_code: str) -> str:
    """Map internal errors to stable, non-sensitive API reason codes."""
    if error_code in {"DUPLICATE_IDENTIFIER", "DUPLICATE_CHARGE"}:
        return "DUPLICATE_CHARGE"
    if error_code in {"FOREIGN_KEY_NOT_FOUND", "IDENTIFIER_CONFLICT"}:
        return "IDENTIFIER_CONFLICT"
    if error_code in {"ORG_MISMATCH", "ORG_CONTEXT_MISSING"}:
        return error_code
    if error_code in {"VALIDATION_ERROR", "MALFORMED_RECORD"}:
        return "MISSING_FIELD" if error_code == "VALIDATION_ERROR" else "DB_ERROR"
    return "DB_ERROR"


def _safe_reason(error: IngestionErrorDetail) -> str:
    """Prevent database/provider exception text from crossing the API boundary."""
    if error.error_code in {"DATABASE_ERROR", "PERSISTENCE_ERROR", "DB_ERROR"}:
        return "Database operation failed"
    if error.error_code == "DUPLICATE_IDENTIFIER" and "Database" in error.reason:
        return "Identifier conflicts with an existing database record"
    return error.reason


def _log_row_exception(message: str, exc: Exception) -> None:
    """Keep full exception details in server logs, never in API row reasons."""
    logger.exception(message, exc_info=exc)


@dataclass
class IngestionResult:
    """Structured report returned after an ingestion operation."""
    record_type: str
    total_records: int
    inserted_count: int
    failed_count: int
    duplicate_count: int
    inserted_ids: List[str] = field(default_factory=list)
    errors: List[IngestionErrorDetail] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to serializable dictionary."""
        error_details = []
        for error in self.errors:
            detail = asdict(error)
            detail["charge_id"] = error.identifier if self.record_type == "charge" else None
            detail["reason"] = _safe_reason(error)
            detail["reason_code"] = _reason_code(error.error_code)
            error_details.append(detail)
        rejected_rows = [
            {
                "row": (error.row_index + 1) if error.row_index is not None else 0,
                "charge_id": error.identifier if self.record_type == "charge" else None,
                "reason": _safe_reason(error),
                "reason_code": _reason_code(error.error_code),
            }
            for error in self.errors
        ]
        return {
            "record_type": self.record_type,
            "total_records": self.total_records,
            "inserted_count": self.inserted_count,
            "failed_count": self.failed_count,
            "accepted_count": self.inserted_count,
            "rejected_count": self.failed_count,
            "duplicate_count": self.duplicate_count,
            "inserted_ids": self.inserted_ids,
            "errors": error_details,
            "total_rows": self.total_records,
            "accepted": self.inserted_count,
            "rejected": self.failed_count,
            "rejected_rows": rejected_rows,
            "by_reason_code": {
                code: sum(1 for error in self.errors if _reason_code(error.error_code) == code)
                for code in sorted({_reason_code(error.error_code) for error in self.errors})
            },
        }


class IngestionService:
    """
    Ingestion layer orchestrator for charges, reimbursements, and evidence.
    Enforces deterministic validation, strict explicit FK resolution, duplicate safety,
    and financial decimal precision.
    """

    # --------------------------------------------------------------------------
    # Charges
    # --------------------------------------------------------------------------
    def ingest_charges(
        self,
        source: Union[str, Path, bytes, IOBase],
        db: Session,
        source_report: Optional[str] = None,
        filename: Optional[str] = None,
        auto_create_containers: bool = False,
    ) -> IngestionResult:
        """Read and ingest charges from a file or stream."""
        if not source_report and filename:
            source_report = filename
        elif not source_report and isinstance(source, (str, Path)):
            source_report = Path(source).name

        records = read_file(source, filename=filename)
        return self.ingest_charges_records(
            records,
            db,
            source_report=source_report,
            auto_create_containers=auto_create_containers,
        )

    def ingest_charges_records(
        self,
        records: List[Dict[str, Any]],
        db: Session,
        source_report: Optional[str] = None,
        auto_create_containers: bool = False,
    ) -> IngestionResult:
        """Ingest a list of raw charge records into the database."""
        record_type = "charge"
        total = len(records)
        logger.info(f"Ingestion started for {record_type} (record_count={total}, source_report={source_report})")
        session_org = current_org(db)
        ingestion_origin = "test" if session_org and session_org.startswith("org_test_") else "judge_data"
        batch_started = perf_counter()

        charge_keys = {
            str(r.get("charge_id") or r.get("line_id") or r.get("fee_id")).strip()
            for r in records if r.get("charge_id") or r.get("line_id") or r.get("fee_id")
        }
        existing_charges = {
            row.charge_id: row for row in db.execute(
                select(Charge.charge_id, Charge.id, Charge.org_id).where(Charge.org_id == session_org, Charge.charge_id.in_(charge_keys))
            )
        } if charge_keys else {}
        shipment_keys = {
            str(r.get("shipment_id") or r.get("fba_shipment_id")).strip()
            for r in records if r.get("shipment_id") or r.get("fba_shipment_id")
        }
        existing_shipments = {
            row.shipment_id: row.id for row in db.execute(
                select(Shipment.shipment_id, Shipment.id).where(Shipment.org_id == session_org, Shipment.shipment_id.in_(shipment_keys))
            )
        } if shipment_keys else {}
        order_keys = {str(r.get("order_id")).strip() for r in records if r.get("order_id")}
        existing_orders = {
            row.order_id: row.id for row in db.execute(
                select(Order.order_id, Order.id).where(Order.org_id == session_org, Order.order_id.in_(order_keys))
            )
        } if order_keys else {}

        inserted_ids: List[str] = []
        errors: List[IngestionErrorDetail] = []
        seen_batch_ids: Set[str] = set()
        duplicate_count = 0
        failed_count = 0

        for idx, raw_record in enumerate(records):
            # 1. Validation & Normalization
            try:
                norm = normalize_charge(raw_record, source_report=source_report, row_index=idx)
            except RecordValidationError as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=exc.identifier,
                        error_code="VALIDATION_ERROR",
                        reason=exc.message,
                    )
                )
                continue
            except Exception as exc:
                _log_row_exception("Charge normalization failed", exc)
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=raw_record.get("charge_id"),
                        error_code="MALFORMED_RECORD",
                        reason=str(exc),
                    )
                )
                continue

            charge_id = norm["charge_id"]

            # All database work for a row is isolated by this savepoint.
            try:
                with db.begin_nested():
                    if charge_id in seen_batch_ids:
                        duplicate_count += 1
                        failed_count += 1
                        errors.append(IngestionErrorDetail(
                            row_index=idx, identifier=charge_id,
                            error_code="DUPLICATE_IDENTIFIER",
                            reason=f"Duplicate charge identifier '{charge_id}' in current batch",
                        ))
                        continue

                    existing = existing_charges.get(charge_id)
                    if existing and existing.org_id == session_org:
                        duplicate_count += 1
                        failed_count += 1
                        errors.append(IngestionErrorDetail(
                            row_index=idx, identifier=charge_id,
                            error_code="DUPLICATE_CHARGE",
                            reason="Charge identifier already exists in this organization",
                        ))
                        continue
                    if existing:
                        failed_count += 1
                        errors.append(IngestionErrorDetail(
                            row_index=idx, identifier=charge_id,
                            error_code="IDENTIFIER_CONFLICT",
                            reason="Charge identifier conflicts with an existing record",
                        ))
                        continue

                    row_org = norm.get("org_id")
                    if not session_org:
                        failed_count += 1
                        errors.append(IngestionErrorDetail(
                            row_index=idx, identifier=charge_id,
                            error_code="ORG_CONTEXT_MISSING",
                            reason="No active organization is set for this ingestion request",
                        ))
                        continue
                    if row_org and row_org != session_org:
                        failed_count += 1
                        errors.append(
                            IngestionErrorDetail(
                                row_index=idx,
                                identifier=charge_id,
                                error_code="ORG_MISMATCH",
                                reason=f"org_id '{row_org}' does not match active organization '{session_org}'",
                            )
                        )
                        continue

                    effective_org = session_org
                    norm["org_id"] = effective_org

                    resolved_shipment_id = None
                    ext_shipment = norm.get("shipment_id")
                    if ext_shipment:
                        shipment_row = existing_shipments.get(ext_shipment)
                        if not shipment_row:
                            if auto_create_containers or "fba_shipment_id" in raw_record or norm.get("unit_id"):
                                new_ship = Shipment(shipment_id=ext_shipment, org_id=effective_org)
                                db.add(new_ship)
                                db.flush()
                                resolved_shipment_id = new_ship.id
                                existing_shipments[ext_shipment] = new_ship.id
                            else:
                                failed_count += 1
                                errors.append(
                                    IngestionErrorDetail(
                                        row_index=idx,
                                        identifier=charge_id,
                                        error_code="IDENTIFIER_CONFLICT",
                                        reason="Referenced shipment identifier was not found",
                                    )
                                )
                                continue
                        else:
                            resolved_shipment_id = shipment_row

                    resolved_order_id = None
                    ext_order = norm.get("order_id")
                    if ext_order:
                        order_row = existing_orders.get(ext_order)
                        if not order_row:
                            if auto_create_containers or norm.get("unit_id"):
                                new_order = Order(order_id=ext_order, org_id=effective_org)
                                db.add(new_order)
                                db.flush()
                                resolved_order_id = new_order.id
                                existing_orders[ext_order] = new_order.id
                            else:
                                failed_count += 1
                                errors.append(
                                    IngestionErrorDetail(
                                        row_index=idx,
                                        identifier=charge_id,
                                        error_code="IDENTIFIER_CONFLICT",
                                        reason="Referenced order identifier was not found",
                                    )
                                )
                                continue
                        else:
                            resolved_order_id = order_row

                    # 5. Model Instantiation & Savepoint Persistence
                    charge_model = Charge(
                        charge_id=charge_id,
                        org_id=effective_org,
                        data_origin=ingestion_origin,
                        unit_id=norm.get("unit_id"),
                        fnsku=norm.get("fnsku"),
                        report_type=norm.get("report_type", "fee_report"),
                        shipment_id=resolved_shipment_id,
                        order_id=resolved_order_id,
                        sku=norm.get("sku"),
                        asin=norm.get("asin"),
                        charge_type=norm["charge_type"],
                        amount=norm["amount"],
                        currency=norm.get("currency", "USD"),
                        charge_date=norm["charge_date"],
                        source_report=norm.get("source_report"),
                        raw_data=norm.get("raw_data", {}),
                        status=norm.get("status", "PENDING"),
                    )

                    db.add(charge_model)
                    db.flush()
                    inserted_ids.append(charge_id)
                    seen_batch_ids.add(charge_id)
            except IntegrityError as exc:
                _log_row_exception("Charge persistence constraint conflict", exc)
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=charge_id,
                        error_code="IDENTIFIER_CONFLICT",
                        reason="Identifier conflicts with an existing database record",
                    )
                )
            except (ProgrammingError, DBAPIError) as exc:
                _log_row_exception("Charge persistence database error", exc)
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=charge_id,
                        error_code="DATABASE_ERROR",
                        reason="Database operation failed",
                    )
                )
            except Exception as exc:
                _log_row_exception("Charge persistence failed", exc)
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=charge_id,
                        error_code="DB_ERROR",
                        reason="Database operation failed",
                    )
                )

        if inserted_ids:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                _log_row_exception("Charge batch commit failed", exc)
                raise IngestionError("Database commit failed") from exc

        inserted_count = len(inserted_ids)
        logger.info(
            f"Ingestion completed for {record_type}: "
            f"total={total}, inserted={inserted_count}, failed={failed_count}, duplicates={duplicate_count}, "
            f"elapsed_seconds={perf_counter() - batch_started:.3f}"
        )

        return IngestionResult(
            record_type=record_type,
            total_records=total,
            inserted_count=inserted_count,
            failed_count=failed_count,
            duplicate_count=duplicate_count,
            inserted_ids=inserted_ids,
            errors=errors,
        )

    # --------------------------------------------------------------------------
    # Reimbursements
    # --------------------------------------------------------------------------
    def ingest_reimbursements(
        self,
        source: Union[str, Path, bytes, IOBase],
        db: Session,
        source_report: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> IngestionResult:
        """Read and ingest reimbursements from a file or stream."""
        if not source_report and filename:
            source_report = filename
        elif not source_report and isinstance(source, (str, Path)):
            source_report = Path(source).name

        records = read_file(source, filename=filename)
        return self.ingest_reimbursements_records(records, db, source_report=source_report)

    def ingest_reimbursements_records(
        self,
        records: List[Dict[str, Any]],
        db: Session,
        source_report: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest a list of raw reimbursement records into the database."""
        record_type = "reimbursement"
        total = len(records)
        logger.info(f"Ingestion started for {record_type} (record_count={total}, source_report={source_report})")
        session_org = current_org(db)
        ingestion_origin = "test" if session_org and session_org.startswith("org_test_") else "judge_data"
        batch_started = perf_counter()
        reimbursement_keys = {str(r.get("reimbursement_id")).strip() for r in records if r.get("reimbursement_id")}
        existing_reimbursements = {
            row.reimbursement_id for row in db.execute(
                select(Reimbursement.reimbursement_id).where(Reimbursement.org_id == session_org, Reimbursement.reimbursement_id.in_(reimbursement_keys))
            )
        } if reimbursement_keys else set()
        charge_keys = {str(r.get("charge_id")).strip() for r in records if r.get("charge_id")}
        existing_charges = {
            row.charge_id: row.id for row in db.execute(
                select(Charge.charge_id, Charge.id).where(Charge.org_id == session_org, Charge.charge_id.in_(charge_keys))
            )
        } if charge_keys else {}

        inserted_ids: List[str] = []
        errors: List[IngestionErrorDetail] = []
        seen_batch_ids: Set[str] = set()
        duplicate_count = 0
        failed_count = 0

        for idx, raw_record in enumerate(records):
            # 1. Validation & Normalization
            try:
                norm = normalize_reimbursement(raw_record, source_report=source_report, row_index=idx)
            except RecordValidationError as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=exc.identifier,
                        error_code="VALIDATION_ERROR",
                        reason=exc.message,
                    )
                )
                continue
            except Exception as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=raw_record.get("reimbursement_id"),
                        error_code="MALFORMED_RECORD",
                        reason=str(exc),
                    )
                )
                continue

            reimbursement_id = norm["reimbursement_id"]

            # 2. Batch-level Duplicate Check
            if reimbursement_id in seen_batch_ids:
                duplicate_count += 1
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=reimbursement_id,
                        error_code="DUPLICATE_IDENTIFIER",
                        reason=f"Duplicate reimbursement identifier '{reimbursement_id}' in current batch",
                    )
                )
                continue

            # 3. Database Duplicate Check
            existing = reimbursement_id in existing_reimbursements
            if existing:
                duplicate_count += 1
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=reimbursement_id,
                        error_code="DUPLICATE_IDENTIFIER",
                        reason=f"Reimbursement with identifier '{reimbursement_id}' already exists in database",
                    )
                )
                continue

            seen_batch_ids.add(reimbursement_id)

            # 4. Explicit Identifier Resolution (charge_id)
            try:
                with db.begin_nested():
                    # Tenant validation
                    row_org = norm.get("org_id")
                    if not session_org:
                        failed_count += 1
                        errors.append(IngestionErrorDetail(
                            row_index=idx,
                            identifier=reimbursement_id,
                            error_code="ORG_CONTEXT_MISSING",
                            reason="No active organization is set for this ingestion request",
                        ))
                        continue
                    if row_org and row_org != session_org:
                        failed_count += 1
                        errors.append(
                            IngestionErrorDetail(
                                row_index=idx,
                                identifier=reimbursement_id,
                                error_code="ORG_MISMATCH",
                                reason=f"org_id '{row_org}' does not match active organization '{session_org}'",
                            )
                        )
                        continue

                    effective_org = session_org
                    norm["org_id"] = effective_org

                    resolved_charge_id = None
                    ext_charge = norm.get("charge_id")
                    if ext_charge:
                        charge_row = existing_charges.get(ext_charge)
                        if not charge_row:
                            failed_count += 1
                            errors.append(
                                IngestionErrorDetail(
                                    row_index=idx,
                                    identifier=reimbursement_id,
                                    error_code="FOREIGN_KEY_NOT_FOUND",
                                    reason=f"Referenced charge_id '{ext_charge}' does not exist",
                                )
                            )
                            continue
                        resolved_charge_id = charge_row

                    # 5. Model Instantiation & Savepoint Persistence
                    reimb_model = Reimbursement(
                        reimbursement_id=reimbursement_id,
                        org_id=effective_org,
                        data_origin=ingestion_origin,
                        charge_id=resolved_charge_id,
                        amount=norm["amount"],
                        reimbursement_date=norm["reimbursement_date"],
                        raw_data=norm.get("raw_data", {}),
                    )

                    db.add(reimb_model)
                    db.flush()
                    inserted_ids.append(reimbursement_id)
            except IntegrityError as exc:
                failed_count += 1
                duplicate_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=reimbursement_id,
                        error_code="DUPLICATE_IDENTIFIER",
                        reason=f"Database uniqueness constraint violated for '{reimbursement_id}': {exc.orig}",
                    )
                )
            except (ProgrammingError, DBAPIError) as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=reimbursement_id,
                        error_code="DATABASE_ERROR",
                        reason=f"Database error for '{reimbursement_id}': {getattr(exc, 'orig', exc)}",
                    )
                )
            except Exception as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=reimbursement_id,
                        error_code="PERSISTENCE_ERROR",
                        reason=str(exc),
                    )
                )

        if inserted_ids:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.error(f"Commit failed for reimbursements batch: {exc}")
                raise IngestionError(f"Database commit failed: {exc}") from exc

        inserted_count = len(inserted_ids)
        logger.info(
            f"Ingestion completed for {record_type}: "
            f"total={total}, inserted={inserted_count}, failed={failed_count}, duplicates={duplicate_count}, "
            f"elapsed_seconds={perf_counter() - batch_started:.3f}"
        )

        return IngestionResult(
            record_type=record_type,
            total_records=total,
            inserted_count=inserted_count,
            failed_count=failed_count,
            duplicate_count=duplicate_count,
            inserted_ids=inserted_ids,
            errors=errors,
        )

    # --------------------------------------------------------------------------
    # Evidence
    # --------------------------------------------------------------------------
    def ingest_evidence(
        self,
        source: Union[str, Path, bytes, IOBase],
        db: Session,
        source_report: Optional[str] = None,
        filename: Optional[str] = None,
        auto_create_containers: bool = False,
    ) -> IngestionResult:
        """Read and ingest evidence from a file or stream."""
        if not source_report and filename:
            source_report = filename
        elif not source_report and isinstance(source, (str, Path)):
            source_report = Path(source).name

        records = read_file(source, filename=filename)
        return self.ingest_evidence_records(
            records,
            db,
            source_report=source_report,
            auto_create_containers=auto_create_containers,
        )

    def ingest_evidence_records(
        self,
        records: List[Dict[str, Any]],
        db: Session,
        source_report: Optional[str] = None,
        auto_create_containers: bool = False,
    ) -> IngestionResult:
        """Ingest a list of raw operational evidence records into the database."""
        record_type = "evidence"
        total = len(records)
        logger.info(f"Ingestion started for {record_type} (record_count={total}, source_report={source_report})")
        session_org = current_org(db)
        ingestion_origin = "test" if session_org and session_org.startswith("org_test_") else "judge_data"
        batch_started = perf_counter()
        evidence_keys = {str(r.get("evidence_id") or r.get("record_id")).strip() for r in records if r.get("evidence_id") or r.get("record_id")}
        existing_evidence = {
            row.evidence_id for row in db.execute(
                select(Evidence.evidence_id).where(Evidence.org_id == session_org, Evidence.evidence_id.in_(evidence_keys))
            )
        } if evidence_keys else set()
        shipment_keys = {
            str(r.get("shipment_id") or r.get("fba_shipment_id")).strip()
            for r in records if r.get("shipment_id") or r.get("fba_shipment_id")
        }
        existing_shipments = {
            row.shipment_id: row.id for row in db.execute(
                select(Shipment.shipment_id, Shipment.id).where(Shipment.org_id == session_org, Shipment.shipment_id.in_(shipment_keys))
            )
        } if shipment_keys else {}
        order_keys = {str(r.get("order_id")).strip() for r in records if r.get("order_id")}
        existing_orders = {
            row.order_id: row.id for row in db.execute(
                select(Order.order_id, Order.id).where(Order.org_id == session_org, Order.order_id.in_(order_keys))
            )
        } if order_keys else {}

        inserted_ids: List[str] = []
        errors: List[IngestionErrorDetail] = []
        seen_batch_ids: Set[str] = set()
        duplicate_count = 0
        failed_count = 0

        for idx, raw_record in enumerate(records):
            # 1. Validation & Normalization
            try:
                norm = normalize_evidence(raw_record, source_report=source_report, row_index=idx)
            except RecordValidationError as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=exc.identifier,
                        error_code="VALIDATION_ERROR",
                        reason=exc.message,
                    )
                )
                continue
            except Exception as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=raw_record.get("evidence_id"),
                        error_code="MALFORMED_RECORD",
                        reason=str(exc),
                    )
                )
                continue

            evidence_id = norm["evidence_id"]

            try:
                with db.begin_nested():
                    if evidence_id in seen_batch_ids:
                        duplicate_count += 1
                        failed_count += 1
                        errors.append(IngestionErrorDetail(
                            row_index=idx, identifier=evidence_id,
                            error_code="DUPLICATE_IDENTIFIER",
                            reason=f"Duplicate evidence identifier '{evidence_id}' in current batch",
                        ))
                        continue

                    existing = evidence_id if evidence_id in existing_evidence else None
                    if existing:
                        duplicate_count += 1
                        failed_count += 1
                        errors.append(IngestionErrorDetail(
                            row_index=idx, identifier=evidence_id,
                            error_code="DUPLICATE_IDENTIFIER",
                            reason=f"Evidence with identifier '{evidence_id}' already exists in database",
                        ))
                        continue

                    row_org = norm.get("org_id")
                    if not session_org:
                        failed_count += 1
                        errors.append(IngestionErrorDetail(
                            row_index=idx, identifier=evidence_id,
                            error_code="ORG_CONTEXT_MISSING",
                            reason="No active organization is set for this ingestion request",
                        ))
                        continue
                    if row_org and row_org != session_org:
                        failed_count += 1
                        errors.append(
                            IngestionErrorDetail(
                                row_index=idx,
                                identifier=evidence_id,
                                error_code="ORG_MISMATCH",
                                reason=f"org_id '{row_org}' does not match active organization '{session_org}'",
                            )
                        )
                        continue

                    effective_org = session_org
                    norm["org_id"] = effective_org

                    resolved_shipment_id = None
                    ext_shipment = norm.get("shipment_id")
                    if ext_shipment:
                        shipment_row = existing_shipments.get(ext_shipment)
                        if not shipment_row:
                            if auto_create_containers or "fba_shipment_id" in raw_record or norm.get("unit_id"):
                                new_ship = Shipment(shipment_id=ext_shipment, org_id=effective_org)
                                db.add(new_ship)
                                db.flush()
                                resolved_shipment_id = new_ship.id
                                existing_shipments[ext_shipment] = new_ship.id
                            else:
                                failed_count += 1
                                errors.append(
                                    IngestionErrorDetail(
                                        row_index=idx,
                                        identifier=evidence_id,
                                        error_code="FOREIGN_KEY_NOT_FOUND",
                                        reason=f"Referenced shipment_id '{ext_shipment}' does not exist",
                                    )
                                )
                                continue
                        else:
                            resolved_shipment_id = shipment_row

                    resolved_order_id = None
                    ext_order = norm.get("order_id")
                    if ext_order:
                        order_row = existing_orders.get(ext_order)
                        if not order_row:
                            if auto_create_containers or norm.get("unit_id"):
                                new_order = Order(order_id=ext_order, org_id=effective_org)
                                db.add(new_order)
                                db.flush()
                                resolved_order_id = new_order.id
                                existing_orders[ext_order] = new_order.id
                            else:
                                failed_count += 1
                                errors.append(
                                    IngestionErrorDetail(
                                        row_index=idx,
                                        identifier=evidence_id,
                                        error_code="FOREIGN_KEY_NOT_FOUND",
                                        reason=f"Referenced order_id '{ext_order}' does not exist",
                                    )
                                )
                                continue
                        else:
                            resolved_order_id = order_row

                    # 5. Model Instantiation & Savepoint Persistence
                    evidence_model = Evidence(
                        evidence_id=evidence_id,
                        org_id=effective_org,
                        data_origin=ingestion_origin,
                        unit_id=norm.get("unit_id"),
                        fnsku=norm.get("fnsku"),
                        source_manager=norm["source_manager"],
                        shipment_id=resolved_shipment_id,
                        order_id=resolved_order_id,
                        sku=norm.get("sku"),
                        asin=norm.get("asin"),
                        evidence_type=norm["evidence_type"],
                        evidence_content=norm["evidence_content"],
                        evidence_timestamp=norm["evidence_timestamp"],
                    )

                    db.add(evidence_model)
                    db.flush()
                    inserted_ids.append(evidence_id)
                    seen_batch_ids.add(evidence_id)
            except IntegrityError as exc:
                failed_count += 1
                duplicate_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=evidence_id,
                        error_code="DUPLICATE_IDENTIFIER",
                        reason=f"Database uniqueness constraint violated for '{evidence_id}': {exc.orig}",
                    )
                )
            except (ProgrammingError, DBAPIError) as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=evidence_id,
                        error_code="DATABASE_ERROR",
                        reason=f"Database error for '{evidence_id}': {getattr(exc, 'orig', exc)}",
                    )
                )
            except Exception as exc:
                failed_count += 1
                errors.append(
                    IngestionErrorDetail(
                        row_index=idx,
                        identifier=evidence_id,
                        error_code="PERSISTENCE_ERROR",
                        reason=str(exc),
                    )
                )

        if inserted_ids:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.error(f"Commit failed for evidence batch: {exc}")
                raise IngestionError(f"Database commit failed: {exc}") from exc

        inserted_count = len(inserted_ids)
        logger.info(
            f"Ingestion completed for {record_type}: "
            f"total={total}, inserted={inserted_count}, failed={failed_count}, duplicates={duplicate_count}, "
            f"elapsed_seconds={perf_counter() - batch_started:.3f}"
        )

        return IngestionResult(
            record_type=record_type,
            total_records=total,
            inserted_count=inserted_count,
            failed_count=failed_count,
            duplicate_count=duplicate_count,
            inserted_ids=inserted_ids,
            errors=errors,
        )

    # --------------------------------------------------------------------------
    # Manager-Specific Evidence Ingestion (Receiving, Prep, Pack, Returns)
    # --------------------------------------------------------------------------
    def ingest_receiving_evidence(
        self,
        source: Union[str, Path, bytes, IOBase],
        db: Session,
        source_report: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest Receiving manager operational evidence."""
        return self.ingest_evidence(
            source=source,
            db=db,
            source_report=source_report or (filename or "receiving_sample.csv"),
            filename=filename or "receiving_sample.csv",
            auto_create_containers=True,
        )

    def ingest_prep_evidence(
        self,
        source: Union[str, Path, bytes, IOBase],
        db: Session,
        source_report: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest Prep manager operational evidence."""
        return self.ingest_evidence(
            source=source,
            db=db,
            source_report=source_report or (filename or "prep_sample.csv"),
            filename=filename or "prep_sample.csv",
            auto_create_containers=True,
        )

    def ingest_pack_evidence(
        self,
        source: Union[str, Path, bytes, IOBase],
        db: Session,
        source_report: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest Pack manager operational evidence."""
        return self.ingest_evidence(
            source=source,
            db=db,
            source_report=source_report or (filename or "pack_sample.csv"),
            filename=filename or "pack_sample.csv",
            auto_create_containers=True,
        )

    def ingest_returns_evidence(
        self,
        source: Union[str, Path, bytes, IOBase],
        db: Session,
        source_report: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest Returns manager operational evidence."""
        return self.ingest_evidence(
            source=source,
            db=db,
            source_report=source_report or (filename or "returns_sample.csv"),
            filename=filename or "returns_sample.csv",
            auto_create_containers=True,
        )


ingestion_service = IngestionService()
