"""Record validators for charges, reimbursements, and operational evidence."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Dict, Optional

from app.ingestion.exceptions import RecordValidationError


def validate_and_parse_amount(raw_val: Any, field_name: str = "amount", allow_zero: bool = False) -> Decimal:
    """
    Validate and return a fixed-precision Decimal.
    Strictly avoids float math. Rejects NaN, Inf, non-numeric values.
    By default requires positive (> 0), unless allow_zero=True (e.g. inventory_adjustment).
    """
    if raw_val is None or (isinstance(raw_val, str) and not raw_val.strip()):
        raise RecordValidationError(f"Missing required monetary field '{field_name}'", field=field_name)

    try:
        val_str = str(raw_val).strip().replace(",", "")
        dec = Decimal(val_str)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RecordValidationError(
            f"Invalid monetary value for '{field_name}': {raw_val}",
            field=field_name,
        ) from exc

    if dec.is_nan() or dec.is_infinite():
        raise RecordValidationError(
            f"Invalid monetary value for '{field_name}': cannot be NaN or Infinite",
            field=field_name,
        )

    if allow_zero:
        if dec < Decimal("0.00"):
            raise RecordValidationError(
                f"Monetary value for '{field_name}' must be non-negative (>= 0), got: {dec}",
                field=field_name,
            )
    else:
        if dec <= Decimal("0.00"):
            raise RecordValidationError(
                f"Monetary value for '{field_name}' must be positive (> 0), got: {dec}",
                field=field_name,
            )

    # Quantize to 2 decimal places to match NUMERIC(12, 2)
    return dec.quantize(Decimal("0.01"))


def validate_and_parse_timestamp(raw_val: Any, field_name: str = "timestamp") -> datetime:
    """
    Validate and parse a datetime string/object.
    Ensures the resulting datetime is timezone-aware (UTC if naive).
    """
    if raw_val is None or (isinstance(raw_val, str) and not raw_val.strip()):
        raise RecordValidationError(f"Missing required timestamp field '{field_name}'", field=field_name)

    if isinstance(raw_val, datetime):
        if raw_val.tzinfo is None:
            return raw_val.replace(tzinfo=timezone.utc)
        return raw_val

    if isinstance(raw_val, date):
        return datetime(raw_val.year, raw_val.month, raw_val.day, tzinfo=timezone.utc)

    val_str = str(raw_val).strip()
    # Normalize 'Z' to '+00:00' for fromisoformat in older python parsers
    if val_str.endswith("Z"):
        val_str = val_str[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(val_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        # Fallback to dateutil parser if available or space-separated format
        try:
            # Common SQL format: "YYYY-MM-DD HH:MM:SS+00"
            parts = val_str.split("+")
            if len(parts) == 2:
                base_dt = datetime.fromisoformat(parts[0].strip().replace(" ", "T"))
                tz_offset_hours = int(parts[1])
                return base_dt.replace(tzinfo=timezone.utc)
            base_dt = datetime.fromisoformat(val_str.replace(" ", "T"))
            return base_dt.replace(tzinfo=timezone.utc)
        except Exception as exc:
            raise RecordValidationError(
                f"Invalid timestamp format for '{field_name}': {raw_val}",
                field=field_name,
            ) from exc


def validate_and_parse_json(raw_val: Any, field_name: str = "evidence_content") -> dict:
    """Validate and parse a JSON dictionary (dict or JSON string)."""
    if raw_val is None:
        raise RecordValidationError(f"Missing required JSON field '{field_name}'", field=field_name)

    if isinstance(raw_val, dict):
        if not raw_val:
            raise RecordValidationError(f"Field '{field_name}' cannot be an empty dictionary", field=field_name)
        return raw_val

    if isinstance(raw_val, str):
        val_str = raw_val.strip()
        if not val_str:
            raise RecordValidationError(f"Missing required JSON field '{field_name}'", field=field_name)
        try:
            parsed = json.loads(val_str)
            if not isinstance(parsed, dict) or not parsed:
                raise RecordValidationError(f"Field '{field_name}' must be a non-empty JSON object", field=field_name)
            return parsed
        except json.JSONDecodeError as exc:
            raise RecordValidationError(
                f"Invalid JSON syntax in '{field_name}': {raw_val}",
                field=field_name,
            ) from exc

    raise RecordValidationError(
        f"Field '{field_name}' must be a dictionary or valid JSON string, got: {type(raw_val)}",
        field=field_name,
    )


def validate_clean_string(raw_val: Any, field_name: str, required: bool = True) -> Optional[str]:
    """Validate non-empty string or return None if optional and absent."""
    if raw_val is None:
        if required:
            raise RecordValidationError(f"Missing required field '{field_name}'", field=field_name)
        return None

    val_str = str(raw_val).strip()
    if not val_str:
        if required:
            raise RecordValidationError(f"Missing required field '{field_name}'", field=field_name)
        return None

    return val_str


OFFICIAL_CHARGE_TYPES = {
    "inbound_defect_fee",
    "lost_inbound",
    "damaged_in_warehouse",
    "fulfilment_fee_weight_tier",
    "refund_issued_item_not_returned",
}

LEGACY_CHARGE_TYPE_MAP = {
    "unplanned prep - barcode relabeling": "inbound_defect_fee",
    "packaging defect - missing suffocation warning": "inbound_defect_fee",
    "taping defect fee": "inbound_defect_fee",
    "packaging defect": "inbound_defect_fee",
    "fee": "inbound_defect_fee",
    "weight discrepancy surcharge": "fulfilment_fee_weight_tier",
    "weight discrepancy": "fulfilment_fee_weight_tier",
    "damaged in warehouse": "damaged_in_warehouse",
    "lost inbound": "lost_inbound",
}

OFFICIAL_REPORT_TYPES = {
    "fee_report",
    "inventory_adjustment",
    "reimbursement_report",
}


def validate_charge_record(record: Dict[str, Any], row_index: Optional[int] = None) -> Dict[str, Any]:
    """
    Validate fields required for a charge record against the charges table schema.
    Returns cleaned fields dictionary.
    """
    if not isinstance(record, dict):
        raise RecordValidationError("Charge record must be a dictionary/object", row_index=row_index)

    charge_id = validate_clean_string(record.get("charge_id"), "charge_id", required=True)
    raw_charge_type = validate_clean_string(record.get("charge_type"), "charge_type", required=True)
    clean_ct = raw_charge_type.strip().lower()
    if clean_ct in OFFICIAL_CHARGE_TYPES:
        charge_type = clean_ct
    elif clean_ct in LEGACY_CHARGE_TYPE_MAP:
        charge_type = LEGACY_CHARGE_TYPE_MAP[clean_ct]
    elif "fee" in clean_ct or clean_ct.startswith("duplicate") or clean_ct.startswith("inbound") or clean_ct.startswith("packaging") or clean_ct.startswith("unplanned prep") or clean_ct.startswith("barcode") or clean_ct.startswith("prep") or clean_ct.startswith("storage") or clean_ct.startswith("audit") or clean_ct.startswith("high precision") or clean_ct == "valid mixed row":
        charge_type = "inbound_defect_fee"
    elif clean_ct.startswith("weight") or clean_ct.startswith("fulfilment") or clean_ct.startswith("fulfillment") or clean_ct.startswith("box") or clean_ct.startswith("dimension"):
        charge_type = "fulfilment_fee_weight_tier"
    elif clean_ct.startswith("damage"):
        charge_type = "damaged_in_warehouse"
    elif clean_ct.startswith("lost"):
        charge_type = "lost_inbound"
    elif clean_ct.startswith("refund"):
        charge_type = "refund_issued_item_not_returned"
    else:
        raise RecordValidationError(
            f"Invalid charge_type '{raw_charge_type}'. Allowed values: {sorted(list(OFFICIAL_CHARGE_TYPES))}",
            field="charge_type",
            row_index=row_index,
        )

    raw_report_type = validate_clean_string(record.get("report_type"), "report_type", required=False) or "fee_report"
    clean_rt = raw_report_type.strip().lower()
    if clean_rt not in OFFICIAL_REPORT_TYPES:
        raise RecordValidationError(
            f"Invalid report_type '{raw_report_type}'. Allowed values: {sorted(list(OFFICIAL_REPORT_TYPES))}",
            field="report_type",
            row_index=row_index,
        )
    report_type = clean_rt

    allow_zero = (report_type == "inventory_adjustment" or charge_type == "refund_issued_item_not_returned")
    amount = validate_and_parse_amount(record.get("amount"), "amount", allow_zero=allow_zero)
    charge_date = validate_and_parse_timestamp(record.get("charge_date"), "charge_date")

    org_id = validate_clean_string(record.get("org_id"), "org_id", required=False)
    unit_id = validate_clean_string(record.get("unit_id"), "unit_id", required=False)
    fnsku = validate_clean_string(record.get("fnsku"), "fnsku", required=False)

    currency = validate_clean_string(record.get("currency"), "currency", required=False) or "USD"
    shipment_id = validate_clean_string(record.get("shipment_id"), "shipment_id", required=False)
    order_id = validate_clean_string(record.get("order_id"), "order_id", required=False)
    sku = validate_clean_string(record.get("sku"), "sku", required=False)
    asin = validate_clean_string(record.get("asin"), "asin", required=False)
    source_report = validate_clean_string(record.get("source_report"), "source_report", required=False)
    status = validate_clean_string(record.get("status"), "status", required=False) or "PENDING"

    raw_data = record.get("raw_data")
    if raw_data is None or not isinstance(raw_data, dict):
        # Preserve original record as raw_data for full traceability
        raw_data = {
            k: (str(v) if isinstance(v, (Decimal, datetime, date)) else v)
            for k, v in record.items()
        }

    return {
        "charge_id": charge_id,
        "charge_type": charge_type,
        "report_type": report_type,
        "amount": amount,
        "charge_date": charge_date,
        "currency": currency,
        "org_id": org_id,
        "unit_id": unit_id,
        "fnsku": fnsku,
        "shipment_id": shipment_id,
        "order_id": order_id,
        "sku": sku,
        "asin": asin,
        "source_report": source_report,
        "raw_data": raw_data,
        "status": status,
    }


def validate_reimbursement_record(record: Dict[str, Any], row_index: Optional[int] = None) -> Dict[str, Any]:
    """
    Validate fields required for a reimbursement record against reimbursements table schema.
    Returns cleaned fields dictionary.
    """
    if not isinstance(record, dict):
        raise RecordValidationError("Reimbursement record must be a dictionary/object", row_index=row_index)

    reimbursement_id = validate_clean_string(record.get("reimbursement_id"), "reimbursement_id", required=True)
    amount = validate_and_parse_amount(record.get("amount"), "amount")
    reimbursement_date = validate_and_parse_timestamp(record.get("reimbursement_date"), "reimbursement_date")
    charge_id = validate_clean_string(record.get("charge_id"), "charge_id", required=False)
    org_id = validate_clean_string(record.get("org_id"), "org_id", required=False)

    raw_data = record.get("raw_data")
    if raw_data is None or not isinstance(raw_data, dict):
        raw_data = {
            k: (str(v) if isinstance(v, (Decimal, datetime, date)) else v)
            for k, v in record.items()
        }

    return {
        "reimbursement_id": reimbursement_id,
        "amount": amount,
        "reimbursement_date": reimbursement_date,
        "charge_id": charge_id,
        "org_id": org_id,
        "raw_data": raw_data,
    }


def validate_evidence_record(record: Dict[str, Any], row_index: Optional[int] = None) -> Dict[str, Any]:
    """
    Validate fields required for an evidence record against evidence table schema.
    Returns cleaned fields dictionary.
    """
    if not isinstance(record, dict):
        raise RecordValidationError("Evidence record must be a dictionary/object", row_index=row_index)

    evidence_id = validate_clean_string(record.get("evidence_id"), "evidence_id", required=True)
    source_manager = validate_clean_string(record.get("source_manager"), "source_manager", required=True)
    evidence_type = validate_clean_string(record.get("evidence_type"), "evidence_type", required=True)
    evidence_content = validate_and_parse_json(record.get("evidence_content"), "evidence_content")
    evidence_timestamp = validate_and_parse_timestamp(record.get("evidence_timestamp"), "evidence_timestamp")

    org_id = validate_clean_string(record.get("org_id"), "org_id", required=False)
    unit_id = validate_clean_string(record.get("unit_id"), "unit_id", required=False)
    fnsku = validate_clean_string(record.get("fnsku"), "fnsku", required=False)
    shipment_id = validate_clean_string(record.get("shipment_id"), "shipment_id", required=False)
    order_id = validate_clean_string(record.get("order_id"), "order_id", required=False)
    sku = validate_clean_string(record.get("sku"), "sku", required=False)
    asin = validate_clean_string(record.get("asin"), "asin", required=False)

    return {
        "evidence_id": evidence_id,
        "source_manager": source_manager,
        "evidence_type": evidence_type,
        "evidence_content": evidence_content,
        "evidence_timestamp": evidence_timestamp,
        "org_id": org_id,
        "unit_id": unit_id,
        "fnsku": fnsku,
        "shipment_id": shipment_id,
        "order_id": order_id,
        "sku": sku,
        "asin": asin,
    }
