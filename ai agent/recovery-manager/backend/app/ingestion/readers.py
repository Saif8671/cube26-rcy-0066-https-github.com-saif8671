"""File readers for CSV, XLSX, and JSON ingestion."""

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from app.ingestion.exceptions import (
    EmptyFileError,
    MalformedFileError,
    UnsupportedFormatError,
)


def _get_bytes_and_ext(
    source: Union[str, Path, bytes, io.IOBase],
    filename: Optional[str] = None,
) -> tuple[bytes, str]:
    """Extract raw bytes and detected file extension from input source."""
    ext = ""
    raw_bytes = b""

    if isinstance(source, (str, Path)):
        path = Path(source)
        if not filename:
            filename = path.name
        ext = path.suffix.lower()
        if not path.exists():
            raise MalformedFileError(f"File not found: {source}")
        try:
            raw_bytes = path.read_bytes()
        except Exception as exc:
            raise MalformedFileError(f"Cannot read file {source}: {exc}") from exc
    elif isinstance(source, bytes):
        raw_bytes = source
        if filename:
            ext = Path(filename).suffix.lower()
    elif isinstance(source, io.IOBase):
        if filename:
            ext = Path(filename).suffix.lower()
        try:
            raw_bytes = source.read()
            if isinstance(raw_bytes, str):
                raw_bytes = raw_bytes.encode("utf-8")
        except Exception as exc:
            raise MalformedFileError(f"Cannot read stream: {exc}") from exc
    else:
        raise UnsupportedFormatError(f"Unsupported source type: {type(source)}")

    if not ext and filename:
        ext = Path(filename).suffix.lower()

    return raw_bytes, ext


KNOWN_BINARY_SIGNATURES = (
    b"MZ",                 # DOS/PE executable (.exe, .dll, .sys)
    b"PK\x03\x04",         # ZIP archive (.zip, .jar, .docx)
    b"\x7fELF",            # ELF binary
    b"\x1f\x8b",           # GZIP archive
    b"%PDF",               # PDF document
    b"7z\xbc\xaf\x27\x1c", # 7-Zip archive
    b"Rar!\x1a\x07",       # RAR archive
)


def read_csv(source: Union[str, Path, bytes, io.IOBase], filename: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Read CSV into a list of dictionaries with column headers as keys.
    Handles UTF-8 and UTF-8 with BOM. Strips header whitespace.
    Rejects binary signatures and NULL bytes.
    """
    raw_bytes, _ = _get_bytes_and_ext(source, filename)
    if not raw_bytes or not raw_bytes.strip():
        raise EmptyFileError("CSV file is empty")

    # Reject known binary file signatures
    for sig in KNOWN_BINARY_SIGNATURES:
        if raw_bytes.startswith(sig):
            raise MalformedFileError("Binary file format detected. CSV files must be valid plain text.")

    # Reject NULL bytes (binary garbage)
    if b"\x00" in raw_bytes[:8192]:
        raise MalformedFileError("Binary data or NULL bytes detected in CSV content.")

    try:
        text_content = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text_content = raw_bytes.decode("latin-1")
            if "\x00" in text_content:
                raise MalformedFileError("Binary data or NULL bytes detected in CSV content.")
        except Exception as exc:
            raise MalformedFileError(f"Failed to decode CSV content: {exc}") from exc

    if not text_content.strip():
        raise EmptyFileError("CSV file is empty")

    try:
        reader = csv.DictReader(io.StringIO(text_content))
        if not reader.fieldnames:
            raise EmptyFileError("CSV file contains no valid headers")

        # Strip header names
        cleaned_fieldnames = [f.strip() if f else "" for f in reader.fieldnames]
        reader.fieldnames = cleaned_fieldnames

        rows: List[Dict[str, Any]] = []
        for raw_row in reader:
            cleaned_row = {}
            has_data = False
            for k, v in raw_row.items():
                if k is None:
                    continue
                k_clean = k.strip()
                v_clean = v.strip() if isinstance(v, str) else v
                if v_clean != "" and v_clean is not None:
                    has_data = True
                cleaned_row[k_clean] = v_clean
            if has_data:
                rows.append(cleaned_row)

        if not rows:
            raise EmptyFileError("CSV file contains headers but no data rows")

        return rows
    except csv.Error as exc:
        raise MalformedFileError(f"Malformed CSV: {exc}") from exc


def read_xlsx(source: Union[str, Path, bytes, io.IOBase], filename: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Read the active sheet of an XLSX workbook into a list of dictionaries.
    Uses openpyxl with data_only=True.
    """
    raw_bytes, _ = _get_bytes_and_ext(source, filename)
    if not raw_bytes or len(raw_bytes) == 0:
        raise EmptyFileError("XLSX file is empty")

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
    except (InvalidFileException, Exception) as exc:
        raise MalformedFileError(f"Malformed XLSX workbook: {exc}") from exc

    sheet = wb.active
    if not sheet:
        raise EmptyFileError("XLSX workbook has no active sheet")

    rows_iter = sheet.iter_rows(values_only=True)
    header_row = None
    for row in rows_iter:
        if any(cell is not None and str(cell).strip() != "" for cell in row):
            header_row = [str(cell).strip() if cell is not None else "" for cell in row]
            break

    if not header_row or not any(h for h in header_row):
        raise EmptyFileError("XLSX sheet contains no valid headers")

    rows: List[Dict[str, Any]] = []
    for row in rows_iter:
        if not any(cell is not None and str(cell).strip() != "" for cell in row):
            continue  # skip empty row
        record: Dict[str, Any] = {}
        has_data = False
        for idx, header in enumerate(header_row):
            if not header:
                continue
            val = row[idx] if idx < len(row) else None
            if isinstance(val, str):
                val = val.strip()
            if val is not None and val != "":
                has_data = True
            record[header] = val
        if has_data:
            rows.append(record)

    if not rows:
        raise EmptyFileError("XLSX sheet contains headers but no data rows")

    return rows


def read_json(source: Union[str, Path, bytes, io.IOBase], filename: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Read JSON input into a list of dictionaries.
    Supports top-level array of objects, or top-level object containing a records array.
    """
    raw_bytes, _ = _get_bytes_and_ext(source, filename)
    if not raw_bytes or not raw_bytes.strip():
        raise EmptyFileError("JSON file is empty")

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedFileError(f"Malformed JSON: {exc}") from exc

    if isinstance(data, list):
        if not data:
            raise EmptyFileError("JSON array contains no records")
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                raise MalformedFileError(f"JSON array item at index {idx} is not an object")
        return data

    if isinstance(data, dict):
        for candidate_key in ("records", "data", "charges", "reimbursements", "evidence", "items"):
            if candidate_key in data and isinstance(data[candidate_key], list):
                record_list = data[candidate_key]
                if not record_list:
                    raise EmptyFileError(f"JSON '{candidate_key}' array is empty")
                for idx, item in enumerate(record_list):
                    if not isinstance(item, dict):
                        raise MalformedFileError(f"Record at index {idx} in '{candidate_key}' is not an object")
                return record_list
        # If no recognized array key, treat single object as a single-record batch
        if not data:
            raise EmptyFileError("JSON object is empty")
        return [data]

    raise MalformedFileError("JSON root must be an array of objects or an object containing a records array")


def read_file(
    source: Union[str, Path, bytes, io.IOBase],
    filename: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Detect format by file extension and read into structured records.
    Supported extensions: .csv, .xlsx, .json
    """
    raw_bytes, ext = _get_bytes_and_ext(source, filename)

    if not ext and isinstance(source, (str, Path)):
        ext = Path(source).suffix.lower()

    if not ext:
        raise UnsupportedFormatError(
            "Cannot determine file format. Please provide a filename with extension (.csv, .xlsx, .json)"
        )

    if ext == ".csv":
        return read_csv(raw_bytes, filename=filename)
    elif ext == ".xlsx":
        return read_xlsx(raw_bytes, filename=filename)
    elif ext == ".json":
        return read_json(raw_bytes, filename=filename)
    else:
        raise UnsupportedFormatError(
            f"Unsupported file format '{ext}'. Supported formats are: .csv, .xlsx, .json"
        )
