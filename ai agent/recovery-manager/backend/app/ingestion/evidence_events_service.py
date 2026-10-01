"""Service for multi-file operational evidence events ingestion and normalization."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.ingestion.exceptions import RecordValidationError
from app.ingestion.readers import read_csv, read_json
from app.ingestion.validators import validate_and_parse_timestamp
from app.models.evidence_event import EvidenceEvent
from app.schemas.ingestion import (
    FileIngestionSummarySchema,
    IngestionErrorDetailSchema,
    MultiFileEvidenceResponseSchema,
)

VALID_EVIDENCE_TYPES = {"receiving", "prep", "pack", "return", "status"}


def infer_evidence_type(filename: str, columns: List[str], explicit_type: Optional[str] = None) -> str:
    """Infer canonical evidence_type from explicit param, filename, or column names."""
    if explicit_type:
        clean = explicit_type.strip().lower()
        if clean in ("returns", "return"):
            return "return"
        if clean in ("receiving", "receiv"):
            return "receiving"
        if clean in VALID_EVIDENCE_TYPES:
            return clean

    fname = (filename or "").lower()
    if "prep" in fname:
        return "prep"
    if "pack" in fname:
        return "pack"
    if "receiv" in fname:
        return "receiving"
    if "return" in fname:
        return "return"
    if "status" in fname:
        return "status"

    # Infer from columns
    cols_lower = [str(c).lower() for c in columns]
    cols_joined = " ".join(cols_lower)
    if any(k in cols_joined for k in ("prep_price", "wo_polybag", "polybag", "suffocation_warning")):
        return "prep"
    if any(k in cols_joined for k in ("cartons_ordered", "po_number", "units_per_carton")):
        return "receiving"
    if any(k in cols_joined for k in ("observed_in_box", "order_lines", "operator_verdict")):
        return "pack"
    if any(k in cols_joined for k in ("parts_list", "parts_missing", "amazon_condition", "operator_disposition")):
        return "return"

    return "status"


def extract_shipment_id(row: Dict[str, Any]) -> Optional[str]:
    """Extract shipment identifier from possible alias fields."""
    for key in (
        "fba_shipment_id",
        "shipment_id",
        "shipmentid",
        "inbound_shipment_id",
        "shipment",
    ):
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()

    # Fallback to container identifiers if shipment is implicit
    for fallback in ("unit_id", "po_number", "order_id"):
        val = row.get(fallback)
        if val is not None and str(val).strip():
            return str(val).strip()

    return None


def extract_timestamp(row: Dict[str, Any], row_idx: int) -> datetime:
    """Extract and parse event timestamp from row using various alias candidates."""
    for key in (
        "captured_at",
        "timestamp",
        "event_time",
        "date",
        "created_at",
        "posted_date",
        "time",
    ):
        val = row.get(key)
        if val is not None and str(val).strip():
            return validate_and_parse_timestamp(val, field_name=key)

    raise RecordValidationError(
        "Missing required event timestamp (checked: captured_at, timestamp, date, event_time)",
        field="timestamp",
        row_index=row_idx,
    )


def extract_status(row: Dict[str, Any]) -> Optional[str]:
    """Extract status or operator outcome."""
    for key in (
        "status",
        "operator_verdict",
        "operator_disposition",
        "observed_state",
        "carton_damage",
        "identity_match",
    ):
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def generate_idempotency_key(
    org_id: str,
    evidence_type: str,
    shipment_id: str,
    ts: datetime,
    filename: str,
    raw_record_id: Optional[str] = None,
) -> str:
    """Generate deterministic hash for re-upload idempotence."""
    raw = f"{org_id}|{evidence_type}|{shipment_id}|{ts.isoformat()}|{filename}|{raw_record_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EvidenceEventsIngestionService:
    """Service handling multi-file evidence event parsing, normalization, and bulk DB persistence."""

    def parse_file_records(
        self,
        file_bytes: bytes,
        filename: str,
    ) -> List[Dict[str, Any]]:
        """Parse CSV or JSON bytes into raw record dictionaries."""
        lower_name = (filename or "").lower()
        if lower_name.endswith(".json"):
            return read_json(file_bytes)
        # Default or .csv
        return read_csv(file_bytes)

    def ingest_single_file(
        self,
        file_bytes: bytes,
        filename: str,
        db: Session,
        explicit_evidence_type: Optional[str] = None,
        org_id: str = "org_demo_alpha",
    ) -> FileIngestionSummarySchema:
        """Ingest single evidence file into evidence_events table."""
        records = self.parse_file_records(file_bytes, filename)
        total = len(records)
        sample_cols = list(records[0].keys()) if records else []
        ev_type = infer_evidence_type(filename, sample_cols, explicit_evidence_type)

        logger.info(
            "Evidence ingestion started: file=%s, type=%s, total=%d, org=%s",
            filename, ev_type, total, org_id,
        )

        candidates: List[Tuple[int, EvidenceEvent, str]] = []
        errors: List[IngestionErrorDetailSchema] = []
        seen_batch_keys = set()
        duplicate_count = 0
        failed_count = 0

        for idx, raw_row in enumerate(records):
            line_no = raw_row.get("_line_number") or (idx + 1)
            raw_rec_id = raw_row.get("record_id") or raw_row.get("unit_id") or raw_row.get("id")

            # 1. Tenant match verification
            row_org = str(raw_row.get("org_id") or org_id).strip()
            if org_id and row_org != org_id:
                failed_count += 1
                reason_msg = f"org_id '{row_org}' does not match active tenant '{org_id}'"
                logger.warning("Evidence tenant mismatch: row=%d file=%s %s", line_no, filename, reason_msg)
                errors.append(
                    IngestionErrorDetailSchema(
                        row=line_no,
                        row_index=line_no,
                        identifier=str(raw_rec_id) if raw_rec_id else None,
                        error_code="TENANT_MISMATCH",
                        reason=reason_msg,
                    )
                )
                continue

            # 2. Extract shipment_id
            shipment_id = extract_shipment_id(raw_row)
            if not shipment_id:
                failed_count += 1
                reason_msg = "Could not resolve shipment identifier from row"
                logger.warning("Evidence missing shipment: row=%d file=%s", line_no, filename)
                errors.append(
                    IngestionErrorDetailSchema(
                        row=line_no,
                        row_index=line_no,
                        identifier=str(raw_rec_id) if raw_rec_id else None,
                        error_code="MISSING_SHIPMENT_ID",
                        reason=reason_msg,
                    )
                )
                continue

            # 3. Extract timestamp
            try:
                event_ts = extract_timestamp(raw_row, line_no)
            except RecordValidationError as exc:
                failed_count += 1
                logger.warning("Evidence timestamp error: row=%d file=%s %s", line_no, filename, exc.message)
                errors.append(
                    IngestionErrorDetailSchema(
                        row=line_no,
                        row_index=line_no,
                        identifier=str(raw_rec_id) if raw_rec_id else None,
                        error_code="INVALID_TIMESTAMP",
                        reason=exc.message,
                    )
                )
                continue
            except Exception as exc:
                failed_count += 1
                logger.warning("Evidence timestamp parse error: row=%d file=%s %s", line_no, filename, exc)
                errors.append(
                    IngestionErrorDetailSchema(
                        row=line_no,
                        row_index=line_no,
                        identifier=str(raw_rec_id) if raw_rec_id else None,
                        error_code="INVALID_TIMESTAMP",
                        reason=str(exc),
                    )
                )
                continue

            # 4. Generate idempotency key
            status_val = extract_status(raw_row)
            idem_key = generate_idempotency_key(
                org_id=row_org,
                evidence_type=ev_type,
                shipment_id=shipment_id,
                ts=event_ts,
                filename=filename,
                raw_record_id=str(raw_rec_id) if raw_rec_id else None,
            )

            # Check intra-batch duplicate
            if idem_key in seen_batch_keys:
                duplicate_count += 1
                continue
            seen_batch_keys.add(idem_key)

            clean_payload = {k: v for k, v in raw_row.items() if not k.startswith("_")}
            event_obj = EvidenceEvent(
                shipment_id=shipment_id,
                evidence_type=ev_type,
                timestamp=event_ts,
                status=status_val,
                source_file=filename,
                raw_payload=clean_payload,
                idempotency_key=idem_key,
                org_id=row_org,
            )
            candidates.append((line_no, event_obj, idem_key))

        # Check existing DB duplicates in batch
        to_insert: List[EvidenceEvent] = []
        if candidates:
            all_keys = [c[2] for c in candidates]
            existing_stmt = select(EvidenceEvent.idempotency_key).where(
                EvidenceEvent.idempotency_key.in_(all_keys)
            )
            existing_keys = set(db.execute(existing_stmt).scalars().all())

            for line_no, event_obj, idem_key in candidates:
                if idem_key in existing_keys:
                    duplicate_count += 1
                else:
                    to_insert.append(event_obj)

        if to_insert:
            try:
                db.add_all(to_insert)
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.exception("Bulk insert failed for evidence events: %s", exc)
                # Fallback to individual savepoints if an unexpected integrity violation occurs
                inserted_single = 0
                for obj in to_insert:
                    try:
                        with db.begin_nested():
                            db.add(obj)
                            db.flush()
                        inserted_single += 1
                    except Exception:
                        duplicate_count += 1
                db.commit()
                to_insert = [None] * inserted_single

        inserted_count = len(to_insert)

        # Counter Exclusivity Check: inserted + duplicates + failed == total
        if inserted_count + duplicate_count + failed_count != total:
            logger.error(
                "Evidence counter invariant violated for file %s: total=%d, inserted=%d, duplicates=%d, failed=%d",
                filename, total, inserted_count, duplicate_count, failed_count,
            )

        logger.info(
            "Evidence ingestion completed for file %s: total=%d, inserted=%d, duplicates=%d, failed=%d",
            filename, total, inserted_count, duplicate_count, failed_count,
        )

        return FileIngestionSummarySchema(
            filename=filename,
            evidence_type=ev_type,
            total=total,
            inserted=inserted_count,
            duplicates=duplicate_count,
            failed=failed_count,
            errors=errors,
        )

    def ingest_multiple_files(
        self,
        files: List[Tuple[bytes, str, Optional[str]]],
        db: Session,
        org_id: str = "org_demo_alpha",
    ) -> MultiFileEvidenceResponseSchema:
        """Ingest multiple evidence files and return aggregated summary."""
        file_summaries: List[FileIngestionSummarySchema] = []
        total_records = 0
        total_inserted = 0
        total_duplicates = 0
        total_failed = 0

        for file_bytes, filename, explicit_type in files:
            summary = self.ingest_single_file(
                file_bytes=file_bytes,
                filename=filename,
                db=db,
                explicit_evidence_type=explicit_type,
                org_id=org_id,
            )
            file_summaries.append(summary)
            total_records += summary.total
            total_inserted += summary.inserted
            total_duplicates += summary.duplicates
            total_failed += summary.failed

        return MultiFileEvidenceResponseSchema(
            total_files=len(files),
            files=file_summaries,
            total_records=total_records,
            total_inserted=total_inserted,
            total_duplicates=total_duplicates,
            total_failed=total_failed,
        )


evidence_events_service = EvidenceEventsIngestionService()
