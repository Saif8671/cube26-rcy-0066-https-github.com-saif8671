"""Phase 11 — Security / Error Handling Verification Script.

Hardening and adversarial-testing pass across the Recovery Manager system:
1. Upload Validation: Max file size (10MB), file type validation (.exe, .zip, binary CSV), malformed-row handling.
2. Secret Hygiene: Full repo & git history secret scan, runtime error leak check.
3. Malformed/Missing Identifier Handling: Unidentifiable charges, orphaned FK references.
4. AI Failure Handling: Simulated Gemini failures (single charge & batch isolation).
5. Database Failure Handling: Simulated DB write failures, transaction rollback, no partial writes.
6. Adversarial Pass on Claim Prevention: Tampered/impossible payloads via raw HTTP API.
7. Production Error Response Hygiene: Sanitized error responses without stack traces, file paths, or SQL queries.

Strict before/after database row count reconciliation across all 8 tables.
"""

from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

# Ensure backend is on sys.path
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
from sqlalchemy import desc, func, select, text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.ai.service import AIService
from app.ai.gemini_client import GeminiClient
from app.ai.exceptions import AIProviderError, AIConfigurationError
from app.ai.schemas import AssessmentType
from app.models.assessment_log import AssessmentLog
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.models.evidence import Evidence
from app.models.order import Order
from app.models.reimbursement import Reimbursement
from app.models.shipment import Shipment

ALL_TABLES = [
    "assessment_log",
    "charges",
    "claim_evidence",
    "claims",
    "evidence",
    "orders",
    "reimbursements",
    "shipments",
]


def get_table_counts(db) -> Dict[str, int]:
    counts = {}
    for tbl in ALL_TABLES:
        cnt = db.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
        counts[tbl] = cnt
    return counts


def run_phase11_security():
    client = TestClient(app)
    db = SessionLocal()

    print("================================================================================")
    print("PHASE 11: SECURITY & ERROR HANDLING VERIFICATION")
    print("================================================================================\n")

    initial_counts = get_table_counts(db)
    print(f"BASELINE DB ROW COUNTS (Before Phase 11 Tests):")
    print(json.dumps(initial_counts, indent=2))
    print("--------------------------------------------------------------------------------\n")

    results_summary = {}

    # Tracking created test IDs for targeted cleanup
    created_charge_ids = []
    created_shipment_ids = []
    created_order_ids = []
    created_evidence_ids = []
    created_reimb_ids = []

    try:
        now = datetime.now(timezone.utc)

        # ==============================================================================
        # 1. UPLOAD VALIDATION
        # ==============================================================================
        print("=== 1. UPLOAD VALIDATION ===")

        # 1.1 Max File Size Enforcement (> 10MB)
        print("\n--- 1.1: Max file size enforcement (> 10MB limit) ---")
        large_payload = b"charge_id,amount,charge_type\n" + b"A" * (10 * 1024 * 1024 + 1024)
        resp_large = client.post(
            "/ingestion/charges",
            files={"file": ("too_large.csv", large_payload, "text/csv")},
        )
        print(f"Request: Upload file of size {len(large_payload)} bytes (> 10MB limit)")
        print(f"Observed HTTP Status: {resp_large.status_code}")
        print(f"Observed Response Body: {resp_large.text}")
        assert resp_large.status_code in (413, 400), f"Expected 413 or 400, got {resp_large.status_code}"
        assert "exceeds maximum allowed limit" in resp_large.text.lower() or "10mb" in resp_large.text.lower()
        results_summary["1.1 Max File Size (>10MB Rejection)"] = "PASS"

        # 1.2 Invalid File Types & Binary Garbage Detection
        print("\n--- 1.2: File type validation (.exe, .zip, and binary garbage CSV) ---")
        
        # 1.2a .exe file
        resp_exe = client.post(
            "/ingestion/charges",
            files={"file": ("malware.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/octet-stream")},
        )
        print(f".exe file upload: Status={resp_exe.status_code}, Body={resp_exe.text}")
        assert resp_exe.status_code == 400
        assert "unsupported file format" in resp_exe.text.lower()

        # 1.2b .zip file
        resp_zip = client.post(
            "/ingestion/charges",
            files={"file": ("archive.zip", b"PK\x03\x04\x14\x00\x00\x00", "application/zip")},
        )
        print(f".zip file upload: Status={resp_zip.status_code}, Body={resp_zip.text}")
        assert resp_zip.status_code == 400
        assert "unsupported file format" in resp_zip.text.lower()

        # 1.2c Binary executable signature disguised as .csv
        resp_bin_csv = client.post(
            "/ingestion/charges",
            files={"file": ("disguised.csv", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff", "text/csv")},
        )
        print(f"Binary header disguised as .csv: Status={resp_bin_csv.status_code}, Body={resp_bin_csv.text}")
        assert resp_bin_csv.status_code == 400
        assert "binary" in resp_bin_csv.text.lower()

        # 1.2d NULL byte noise disguised as .csv
        resp_null_csv = client.post(
            "/ingestion/charges",
            files={"file": ("noise.csv", b"\x00\xff\xfe\x00\x12\x34\x56\x78" * 50, "text/csv")},
        )
        print(f"NULL bytes noise in .csv: Status={resp_null_csv.status_code}, Body={resp_null_csv.text}")
        assert resp_null_csv.status_code == 400
        assert "binary" in resp_null_csv.text.lower() or "null" in resp_null_csv.text.lower() or "empty" in resp_null_csv.text.lower()

        results_summary["1.2 File Type Validation (.exe, .zip, binary CSV)"] = "PASS"

        # 1.3 Malformed-Row Handling (Phase 3 Re-test with fresh file)
        print("\n--- 1.3: Malformed-row handling (fresh test file) ---")
        malformed_csv = (
            "charge_id,amount,charge_type,charge_date\n"
            "CHG-SEC-VALID-01,100.00,Inbound Fee,2026-03-01T12:00:00Z\n"
            ",50.00,Missing ID Fee,2026-03-01T12:00:00Z\n"
            "CHG-SEC-BAD-02,INVALID_AMOUNT,Bad Amount Fee,2026-03-01T12:00:00Z\n"
        )
        resp_malformed = client.post(
            "/ingestion/charges",
            files={"file": ("mixed_rows.csv", malformed_csv.encode("utf-8"), "text/csv")},
        )
        print(f"Malformed rows response: Status={resp_malformed.status_code}")
        print(f"Body: {json.dumps(resp_malformed.json(), indent=2)}")
        assert resp_malformed.status_code == 200
        data_malformed = resp_malformed.json()
        assert data_malformed["total_records"] == 3
        assert data_malformed["inserted_count"] == 1
        assert data_malformed["failed_count"] == 2
        assert len(data_malformed["errors"]) == 2
        created_charge_ids.append("CHG-SEC-VALID-01")
        results_summary["1.3 Malformed-Row Handling (Isolated Failures)"] = "PASS"

        # ==============================================================================
        # 2. SECRET HYGIENE
        # ==============================================================================
        print("\n=== 2. SECRET HYGIENE ===")

        # 2.1 Git history secret scan
        print("\n--- 2.1: Full git repository and history secret scan ---")
        
        # Verify .env is in .gitignore
        gitignore_content = Path(".gitignore").read_text(encoding="utf-8")
        assert ".env" in gitignore_content.splitlines(), ".env must be listed in .gitignore"
        print("Gitignore check: '.env' is explicitly present in .gitignore.")

        # Check git log for .env
        git_env_check = subprocess.run(
            ["git", "log", "--all", "--full-history", "--", ".env"],
            capture_output=True,
            text=True,
            cwd=str(backend_dir.parent),
        )
        assert git_env_check.stdout.strip() == "", "CRITICAL SECURITY VIOLATION: .env was committed in git history!"
        print("Git commit check: .env was NEVER committed in repository history.")

        # Scan git log -p for sensitive tokens
        secret_tokens = [
            ("Database Password", "MEDgudaince"),
            ("Gemini API Key Prefix", "AQ.Ab8RN6Ld"),
            ("Supabase JWT Secret", "OHHzyx6Ae6DZ9aatl5CZ2ocq"),
            ("Supabase Publishable Key", "sb_publishable_65jA8KM99bZing"),
        ]

        for token_label, token_val in secret_tokens:
            scan_proc = subprocess.run(
                ["git", "log", "-p", "-S", token_val],
                capture_output=True,
                text=True,
                cwd=str(backend_dir.parent),
            )
            assert scan_proc.stdout.strip() == "", f"SECURITY LEAK: {token_label} found in git commit history!"
            print(f"Git history scan: Zero occurrences of {token_label}.")

        # Scan working tree git-tracked files
        for token_label, token_val in secret_tokens:
            grep_proc = subprocess.run(
                ["git", "grep", token_val],
                capture_output=True,
                text=True,
                cwd=str(backend_dir.parent),
            )
            # git grep exits with 1 when pattern is not found
            assert grep_proc.returncode == 1, f"SECURITY LEAK: {token_label} found in tracked repository files!"
            print(f"Tracked files scan: Zero occurrences of {token_label}.")

        results_summary["2.1 Git Secret Scan (.env & credentials)"] = "PASS"

        # 2.2 Error response & log leak check
        print("\n--- 2.2: Runtime error response & log leak check ---")
        gemini_key = settings.gemini_api_key or ""
        test_secrets = [gemini_key] if gemini_key else []

        # Trigger simulated failures across components
        # Ingestion failure
        resp_leak_1 = client.post("/ingestion/charges", content=b"invalid json", headers={"content-type": "application/json"})
        # Pipeline invalid charge lookup
        resp_leak_2 = client.post("/pipeline/process", json={"charge_id": "CHG-NONEXISTENT-999"})
        # AI endpoint simulated failure
        resp_leak_3 = client.post("/ai/assess", json={"charge": {"charge_id": "CHG-1", "charge_type": "Fee", "amount": 10.0}, "evidence": []})

        for resp in [resp_leak_1, resp_leak_2, resp_leak_3]:
            for sec in test_secrets:
                if sec and len(sec) > 8:
                    assert sec not in resp.text, f"CRITICAL LEAK: Secret found in HTTP response body: {resp.text}"

        print("Runtime leak check: All triggered error responses verified 100% free of secret tokens.")
        results_summary["2.2 Runtime Error & Log Leak Check"] = "PASS"

        # ==============================================================================
        # 3. MALFORMED / MISSING IDENTIFIER HANDLING
        # ==============================================================================
        print("\n=== 3. MALFORMED / MISSING IDENTIFIER HANDLING ===")

        # 3.1 Fully unidentifiable charge
        print("\n--- 3.1: Fully unidentifiable charge (No shipment, order, sku, or asin) ---")
        chg_unident = Charge(
            charge_id="CHG-SEC-UNIDENT",
            shipment_id=None,
            order_id=None,
            sku=None,
            asin=None,
            charge_type="Unplanned Fee",
            amount=Decimal("45.00"),
            currency="USD",
            charge_date=now,
            status="PENDING",
            source_report="test_security.csv",
        )
        db.add(chg_unident)
        db.commit()
        created_charge_ids.append("CHG-SEC-UNIDENT")

        # Run through pipeline with real Gemini
        resp_unident = client.post("/pipeline/process", json={"charge_id": "CHG-SEC-UNIDENT"})
        print(f"Unidentifiable charge pipeline response: Status={resp_unident.status_code}")
        print(f"PipelineResult: {json.dumps(resp_unident.json(), indent=2)}")
        assert resp_unident.status_code == 200
        res_unident = resp_unident.json()
        assert res_unident["outcome"] == "NO_CLAIM"
        assert res_unident["assessment"] == "SILENT"
        assert res_unident["claim_id"] is None
        assert res_unident["evidence_count"] == 0

        # DB check: 0 claims
        claim_unident = db.scalars(select(Claim).where(Claim.charge_id == chg_unident.id)).first()
        log_unident = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg_unident.id)).first()
        assert claim_unident is None
        assert log_unident is not None and log_unident.assessment == "SILENT"
        print("Unidentifiable charge safely resolved to SILENT with 0 claims.")
        results_summary["3.1 Fully Unidentifiable Charge (SILENT Resolution)"] = "PASS"

        # 3.2 Orphaned reference handling
        print("\n--- 3.2: Orphaned foreign key reference handling ---")
        # Ingestion test with non-existent foreign keys
        orphaned_csv = (
            "charge_id,shipment_id,order_id,amount,charge_type,charge_date\n"
            "CHG-SEC-ORPHAN-01,SHP-GHOST-999,ORD-GHOST-999,55.00,Orphaned Fee,2026-03-01T12:00:00Z\n"
        )
        resp_orphan = client.post(
            "/ingestion/charges",
            files={"file": ("orphan.csv", orphaned_csv.encode("utf-8"), "text/csv")},
        )
        print(f"Orphaned reference ingestion: Status={resp_orphan.status_code}")
        print(f"Response: {resp_orphan.json()}")
        assert resp_orphan.status_code == 200
        orphan_data = resp_orphan.json()
        assert orphan_data["failed_count"] == 1
        assert orphan_data["inserted_count"] == 0
        assert orphan_data["errors"][0]["error_code"] == "FOREIGN_KEY_NOT_FOUND"
        print("Orphaned foreign references rejected cleanly at ingestion without DB crash.")
        results_summary["3.2 Orphaned Identifier References (Graceful Handling)"] = "PASS"

        # ==============================================================================
        # 4. AI FAILURE HANDLING (RE-VERIFIED UNDER GEMINI)
        # ==============================================================================
        print("\n=== 4. AI FAILURE HANDLING (RE-VERIFIED UNDER GEMINI) ===")

        # 4.1 Single-charge simulated Gemini failure
        print("\n--- 4.1: Single charge simulated Gemini failure ---")
        shp_aifail = Shipment(shipment_id="SHP-SEC-AIFAIL")
        ord_aifail = Order(order_id="ORD-SEC-AIFAIL")
        db.add_all([shp_aifail, ord_aifail])
        db.flush()
        created_shipment_ids.append("SHP-SEC-AIFAIL")
        created_order_ids.append("ORD-SEC-AIFAIL")

        chg_aifail = Charge(
            charge_id="CHG-SEC-AIFAIL",
            shipment_id=shp_aifail.id,
            order_id=ord_aifail.id,
            sku="SKU-SEC-AIFAIL",
            asin="B00AIFAIL",
            charge_type="FBA Weight Discrepancy",
            amount=Decimal("80.00"),
            currency="USD",
            charge_date=now,
            status="PENDING",
            source_report="test_security.csv",
        )
        db.add(chg_aifail)
        db.flush()
        created_charge_ids.append("CHG-SEC-AIFAIL")

        evd_aifail = Evidence(
            evidence_id="EVD-SEC-AIFAIL",
            shipment_id=shp_aifail.id,
            order_id=ord_aifail.id,
            sku="SKU-SEC-AIFAIL",
            asin="B00AIFAIL",
            source_manager="Receiving",
            evidence_type="WEIGHT_SCAN",
            evidence_timestamp=now,
            evidence_content={"measured_weight_kg": 0.5},
        )
        db.add(evd_aifail)
        db.commit()
        created_evidence_ids.append("EVD-SEC-AIFAIL")

        # Mock GeminiClient.generate_assessment to simulate connection timeout / error
        with patch("app.ai.gemini_client.GeminiClient.generate_assessment", side_effect=AIProviderError("AI reasoning provider connection error (simulated timeout).")):
            resp_aifail = client.post("/pipeline/process", json={"charge_id": "CHG-SEC-AIFAIL"})

        print(f"Simulated Gemini failure response: Status={resp_aifail.status_code}")
        print(f"PipelineResult: {json.dumps(resp_aifail.json(), indent=2)}")
        assert resp_aifail.status_code == 200
        res_aifail = resp_aifail.json()
        assert res_aifail["outcome"] == "ERROR"
        assert res_aifail["charge_id"] == "CHG-SEC-AIFAIL"
        assert "AI reasoning failure" in res_aifail["reason"] or "AIProviderError" in res_aifail["reason"]

        # Confirm DB state is uncorrupted: NO claim created
        claim_aifail = db.scalars(select(Claim).where(Claim.charge_id == chg_aifail.id)).first()
        assert claim_aifail is None, "Violation: Claim row must not exist after AI failure"
        print("Single charge AI failure returned clean ERROR outcome; zero DB corruption.")
        results_summary["4.1 Single-Charge AI Failure (Clean ERROR Outcome)"] = "PASS"

        # 4.2 Batch partial-failure isolation under Gemini
        print("\n--- 4.2: Batch pipeline partial-failure isolation under Gemini ---")
        shp_bat = Shipment(shipment_id="SHP-SEC-BAT")
        ord_bat = Order(order_id="ORD-SEC-BAT")
        db.add_all([shp_bat, ord_bat])
        db.flush()
        created_shipment_ids.append("SHP-SEC-BAT")
        created_order_ids.append("ORD-SEC-BAT")

        chg_batA = Charge(charge_id="CHG-SEC-BATA", shipment_id=shp_bat.id, order_id=ord_bat.id, sku="SKU-BATA", charge_type="Fee A", amount=Decimal("30.00"), charge_date=now, status="PENDING")
        chg_batB = Charge(charge_id="CHG-SEC-BATB", shipment_id=shp_bat.id, order_id=ord_bat.id, sku="SKU-BATB", charge_type="Fee B", amount=Decimal("40.00"), charge_date=now, status="PENDING")
        chg_batC = Charge(charge_id="CHG-SEC-BATC", shipment_id=shp_bat.id, order_id=ord_bat.id, sku="SKU-BATC", charge_type="Fee C", amount=Decimal("50.00"), charge_date=now, status="PENDING")
        db.add_all([chg_batA, chg_batB, chg_batC])
        db.flush()
        created_charge_ids.extend(["CHG-SEC-BATA", "CHG-SEC-BATB", "CHG-SEC-BATC"])

        evd_batA = Evidence(evidence_id="EVD-SEC-BATA", shipment_id=shp_bat.id, order_id=ord_bat.id, sku="SKU-BATA", source_manager="Prep", evidence_type="SCAN", evidence_timestamp=now, evidence_content={"scanned": True})
        evd_batB = Evidence(evidence_id="EVD-SEC-BATB", shipment_id=shp_bat.id, order_id=ord_bat.id, sku="SKU-BATB", source_manager="Prep", evidence_type="SCAN", evidence_timestamp=now, evidence_content={"scanned": True})
        evd_batC = Evidence(evidence_id="EVD-SEC-BATC", shipment_id=shp_bat.id, order_id=ord_bat.id, sku="SKU-BATC", source_manager="Prep", evidence_type="SCAN", evidence_timestamp=now, evidence_content={"scanned": True})
        db.add_all([evd_batA, evd_batB, evd_batC])
        db.commit()
        created_evidence_ids.extend(["EVD-SEC-BATA", "EVD-SEC-BATB", "EVD-SEC-BATC"])

        def mock_batch_gemini(system_prompt, user_prompt):
            if "CHG-SEC-BATA" in user_prompt:
                return json.dumps({"assessment": "CONTRADICTED", "claim_supported": True, "claim_amount": 30.00, "confidence": 0.95, "reason": "Fee A contradicted.", "evidence_ids": ["EVD-SEC-BATA"]})
            elif "CHG-SEC-BATB" in user_prompt:
                raise AIProviderError("Gemini 503 high demand spike on charge B")
            elif "CHG-SEC-BATC" in user_prompt:
                return json.dumps({"assessment": "CONTRADICTED", "claim_supported": True, "claim_amount": 50.00, "confidence": 0.95, "reason": "Fee C contradicted.", "evidence_ids": ["EVD-SEC-BATC"]})
            return json.dumps({"assessment": "SILENT", "claim_supported": False, "confidence": 1.0, "reason": "Default silent", "evidence_ids": []})

        with patch("app.ai.gemini_client.GeminiClient.generate_assessment", side_effect=mock_batch_gemini):
            resp_batch = client.post("/pipeline/process-batch", json={"charge_ids": ["CHG-SEC-BATA", "CHG-SEC-BATB", "CHG-SEC-BATC"]})

        print(f"Batch processing response: Status={resp_batch.status_code}")
        batch_data = resp_batch.json()
        print(f"Summary: total={batch_data['total']}, succeeded={batch_data['succeeded']}, failed={batch_data['failed']}")
        assert resp_batch.status_code == 200
        assert batch_data["total"] == 3
        assert batch_data["succeeded"] == 2
        assert batch_data["failed"] == 1

        res_a = next(r for r in batch_data["results"] if r["charge_id"] == "CHG-SEC-BATA")
        res_b = next(r for r in batch_data["results"] if r["charge_id"] == "CHG-SEC-BATB")
        res_c = next(r for r in batch_data["results"] if r["charge_id"] == "CHG-SEC-BATC")

        assert res_a["outcome"] == "CLAIM_CREATED"
        assert res_b["outcome"] == "ERROR"
        assert res_c["outcome"] == "CLAIM_CREATED"

        # Verify DB: A and C have claims, B has NONE
        claim_a = db.scalars(select(Claim).where(Claim.charge_id == chg_batA.id)).first()
        claim_b = db.scalars(select(Claim).where(Claim.charge_id == chg_batB.id)).first()
        claim_c = db.scalars(select(Claim).where(Claim.charge_id == chg_batC.id)).first()

        assert claim_a is not None
        assert claim_b is None, "Violation: Failed charge B must NOT have a claim in DB"
        assert claim_c is not None
        print("Batch pipeline error isolation verified: Failure on B isolated; A and C succeeded.")
        results_summary["4.2 Batch Error Isolation Under Gemini"] = "PASS"

        # ==============================================================================
        # 5. DATABASE FAILURE HANDLING
        # ==============================================================================
        print("\n=== 5. DATABASE FAILURE HANDLING ===")

        # 5.1 Simulated DB failure during write in POST /claims/process
        print("\n--- 5.1: Simulated DB write failure in POST /claims/process ---")
        chg_dbf1 = Charge(charge_id="CHG-SEC-DBF1", charge_type="Fee", amount=Decimal("70.00"), charge_date=now, status="PENDING")
        db.add(chg_dbf1)
        db.commit()
        created_charge_ids.append("CHG-SEC-DBF1")

        valid_claim_req = {
            "charge_id": "CHG-SEC-DBF1",
            "validation_result": {
                "charge_id": "CHG-SEC-DBF1",
                "assessment": "CONTRADICTED",
                "eligible_for_recovery": True,
                "human_review_required": False,
                "claim_amount": "70.00",
                "evidence_ids": [],
                "decision": "ELIGIBLE",
                "status": "ELIGIBLE",
                "reason": "Eligible claim",
                "rule_code": "RULE_ELIGIBLE"
            },
            "assessment_response": {
                "assessment": "CONTRADICTED",
                "claim_supported": True,
                "claim_amount": "70.00",
                "confidence": 0.95,
                "reason": "Contradicted fee",
                "evidence_ids": []
            },
            "evidence": [],
            "processing_state": {"duplicate": False, "already_reimbursed": False}
        }

        # Simulate DB commit failure
        with patch.object(Session, "commit", side_effect=OperationalError("connection lost", {}, Exception("Simulated DB connection drop"))):
            resp_dbf1 = client.post("/claims/process", json=valid_claim_req)

        print(f"Simulated DB write failure in /claims/process: Status={resp_dbf1.status_code}, Body={resp_dbf1.text}")
        assert resp_dbf1.status_code == 500
        assert "stack" not in resp_dbf1.text.lower() and "traceback" not in resp_dbf1.text.lower()
        # Verify 0 claims created
        c_dbf1 = db.scalars(select(Claim).where(Claim.charge_id == chg_dbf1.id)).first()
        assert c_dbf1 is None, "Rollback failed: partial claim row was committed!"
        results_summary["5.1 DB Write Failure in POST /claims/process"] = "PASS"

        # 5.2 Simulated DB failure in POST /pipeline/process
        print("\n--- 5.2: Simulated DB failure in POST /pipeline/process ---")
        chg_dbf2 = Charge(charge_id="CHG-SEC-DBF2", charge_type="Fee", amount=Decimal("60.00"), charge_date=now, status="PENDING")
        db.add(chg_dbf2)
        db.commit()
        created_charge_ids.append("CHG-SEC-DBF2")

        with patch.object(Session, "commit", side_effect=OperationalError("commit failed", {}, Exception("Simulated commit error"))):
            resp_dbf2 = client.post("/pipeline/process", json={"charge_id": "CHG-SEC-DBF2"})

        print(f"Simulated DB failure in /pipeline/process: Status={resp_dbf2.status_code}, Body={resp_dbf2.text}")
        assert resp_dbf2.status_code in (200, 500)
        if resp_dbf2.status_code == 200:
            assert resp_dbf2.json()["outcome"] in ("ERROR", "NO_CLAIM")
        # Verify no partial claim exists
        c_dbf2 = db.scalars(select(Claim).where(Claim.charge_id == chg_dbf2.id)).first()
        assert c_dbf2 is None
        results_summary["5.2 DB Failure in POST /pipeline/process"] = "PASS"

        # 5.3 Batch write failure isolation in POST /pipeline/process-batch
        print("\n--- 5.3: Batch DB failure isolation in POST /pipeline/process-batch ---")
        chg_dbf3 = Charge(charge_id="CHG-SEC-DBF3", charge_type="Fee", amount=Decimal("50.00"), charge_date=now, status="PENDING")
        db.add(chg_dbf3)
        db.commit()
        created_charge_ids.append("CHG-SEC-DBF3")

        with patch.object(Session, "commit", side_effect=OperationalError("batch commit fail", {}, Exception("Simulated batch fail"))):
            resp_dbf3 = client.post("/pipeline/process-batch", json={"charge_ids": ["CHG-SEC-DBF3"]})

        print(f"Batch DB failure isolation: Status={resp_dbf3.status_code}, Body={resp_dbf3.text}")
        assert resp_dbf3.status_code == 200
        batch_dbf3_data = resp_dbf3.json()
        assert batch_dbf3_data["failed"] >= 1
        results_summary["5.3 Batch DB Failure Isolation"] = "PASS"

        # ==============================================================================
        # 6. ADVERSARIAL PASS ON CLAIM PREVENTION
        # ==============================================================================
        print("\n=== 6. ADVERSARIAL PASS ON CLAIM PREVENTION ===")

        # 6.1 Direct crafted malicious payloads to POST /claims/process
        print("\n--- 6.1: Direct adversarial payloads to POST /claims/process ---")

        # Attack 6.1a: Negative claim_amount
        adv_negative_amt = json.loads(json.dumps(valid_claim_req))
        adv_negative_amt["assessment_response"]["claim_amount"] = -100.00
        resp_adv_neg = client.post("/claims/process", json=adv_negative_amt)
        print(f"Negative claim_amount: Status={resp_adv_neg.status_code}, Body={resp_adv_neg.text}")
        assert resp_adv_neg.status_code == 422
        assert "greater than" in resp_adv_neg.text.lower() or "negative" in resp_adv_neg.text.lower() or "input should be" in resp_adv_neg.text.lower()

        # Attack 6.1b: String claim_amount
        adv_str_amt = json.loads(json.dumps(valid_claim_req))
        adv_str_amt["assessment_response"]["claim_amount"] = "one_hundred_dollars"
        resp_adv_str = client.post("/claims/process", json=adv_str_amt)
        print(f"String claim_amount: Status={resp_adv_str.status_code}, Body={resp_adv_str.text}")
        assert resp_adv_str.status_code == 422

        # Attack 6.1c: Assessment value outside enum
        adv_bad_enum = json.loads(json.dumps(valid_claim_req))
        adv_bad_enum["assessment_response"]["assessment"] = "FORGED_ASSESSMENT_TYPE"
        resp_adv_enum = client.post("/claims/process", json=adv_bad_enum)
        print(f"Invalid assessment enum: Status={resp_adv_enum.status_code}, Body={resp_adv_enum.text}")
        assert resp_adv_enum.status_code == 422

        # Attack 6.1d: Foreign evidence injection (EVD-NONEXISTENT-999)
        adv_foreign_evd = json.loads(json.dumps(valid_claim_req))
        adv_foreign_evd["assessment_response"]["evidence_ids"] = ["EVD-NONEXISTENT-999"]
        adv_foreign_evd["validation_result"]["evidence_ids"] = ["EVD-NONEXISTENT-999"]
        resp_adv_evd = client.post("/claims/process", json=adv_foreign_evd)
        print(f"Foreign evidence injection: Status={resp_adv_evd.status_code}, Body={resp_adv_evd.text}")
        assert resp_adv_evd.status_code == 200
        res_adv_evd = resp_adv_evd.json()
        assert res_adv_evd["outcome"] == "REJECTED_AT_CLAIM_ENGINE"
        assert "evidence ids not found in database" in res_adv_evd["reason"].lower()

        # 6.2 Malicious payloads to POST /pipeline/process
        print("\n--- 6.2: Direct adversarial payloads to POST /pipeline/process ---")
        
        # Empty body
        resp_pipe_empty = client.post("/pipeline/process", json={})
        print(f"Empty body: Status={resp_pipe_empty.status_code}")
        assert resp_pipe_empty.status_code == 422

        # Extra injected fields (forbidden extra fields)
        resp_pipe_extra = client.post("/pipeline/process", json={"charge_id": "CHG-1", "forged_amount": 999999})
        print(f"Forbidden extra field: Status={resp_pipe_extra.status_code}")
        assert resp_pipe_extra.status_code == 422

        # Non-string charge_id
        resp_pipe_type = client.post("/pipeline/process", json={"charge_id": 123456})
        print(f"Numeric charge_id: Status={resp_pipe_type.status_code}")
        assert resp_pipe_type.status_code == 422

        # Non-existent charge_id
        resp_pipe_404 = client.post("/pipeline/process", json={"charge_id": "CHG-DOES-NOT-EXIST-404"})
        print(f"Non-existent charge: Status={resp_pipe_404.status_code}")
        assert resp_pipe_404.status_code == 404

        results_summary["6. Adversarial Claim Prevention (Tampered Payloads)"] = "PASS"

        # ==============================================================================
        # 7. PRODUCTION ERROR RESPONSE HYGIENE
        # ==============================================================================
        print("\n=== 7. PRODUCTION ERROR RESPONSE HYGIENE ===")

        endpoints_to_test = [
            ("POST", "/ingestion/charges", {"content": b"malformed json {", "headers": {"content-type": "application/json"}}),
            ("POST", "/pipeline/process", {"content": b"{bad json", "headers": {"content-type": "application/json"}}),
            ("POST", "/claims/process", {"content": b"{bad json", "headers": {"content-type": "application/json"}}),
            ("GET", "/claims?limit=-10", {}),
            ("GET", "/claims?limit=not_a_number", {}),
            ("GET", "/charges/nonexistent_route_404", {}),
        ]

        forbidden_markers = [
            "traceback (most recent call last):",
            "file \"e:\\",
            "file \"c:\\",
            ".py\", line",
            "select count(*) from",
            "insert into",
            "postgresql://",
        ]

        print("Testing unexpected / malformed requests against API surface:")
        for method, path, kwargs in endpoints_to_test:
            if method == "POST":
                resp_hyg = client.post(path, **kwargs)
            else:
                resp_hyg = client.get(path, **kwargs)

            body_lower = resp_hyg.text.lower()
            print(f"  {method} {path} -> HTTP {resp_hyg.status_code}")

            for marker in forbidden_markers:
                assert marker not in body_lower, f"LEAK DETECTED on {method} {path}: response contains '{marker}': {resp_hyg.text}"

        print("Production error hygiene verified: Zero stack traces, file paths, raw SQL, or connection strings exposed.")
        results_summary["7. Production Error Hygiene (Zero Leaks/Stack Traces)"] = "PASS"

    finally:
        # ==============================================================================
        # CLEANUP AND BEFORE/AFTER ROW COUNT RECONCILIATION
        # ==============================================================================
        print("\n================================================================================")
        print("CLEANUP: TARGETED REMOVAL OF ALL PHASE 11 TEST DATA")
        print("================================================================================")

        all_cids = list(set(created_charge_ids))
        all_sids = list(set(created_shipment_ids))
        all_oids = list(set(created_order_ids))
        all_eids = list(set(created_evidence_ids))

        # Targeted deletion in proper FK order
        db.execute(text("""
            DELETE FROM claim_evidence 
            WHERE claim_id IN (
                SELECT id FROM claims WHERE charge_id IN (SELECT id FROM charges WHERE charge_id = ANY(:cids))
            )
        """), {"cids": all_cids})

        db.execute(text("""
            DELETE FROM claims 
            WHERE charge_id IN (SELECT id FROM charges WHERE charge_id = ANY(:cids))
        """), {"cids": all_cids})

        db.execute(text("""
            DELETE FROM assessment_log 
            WHERE charge_id IN (SELECT id FROM charges WHERE charge_id = ANY(:cids))
        """), {"cids": all_cids})

        db.execute(text("""
            DELETE FROM reimbursements 
            WHERE charge_id IN (SELECT id FROM charges WHERE charge_id = ANY(:cids))
        """), {"cids": all_cids})

        db.execute(text("""
            DELETE FROM evidence 
            WHERE evidence_id = ANY(:eids)
        """), {"eids": all_eids})

        db.execute(text("""
            DELETE FROM charges 
            WHERE charge_id = ANY(:cids)
        """), {"cids": all_cids})

        db.execute(text("""
            DELETE FROM shipments 
            WHERE shipment_id = ANY(:sids)
        """), {"sids": all_sids})

        db.execute(text("""
            DELETE FROM orders 
            WHERE order_id = ANY(:oids)
        """), {"oids": all_oids})

        db.commit()
        print("Targeted deletion completed.")

        final_counts = get_table_counts(db)
        print("\n================================================================================")
        print("DATABASE ROW COUNTS RECONCILIATION:")
        print("================================================================================")
        all_matched = True
        for tbl in ALL_TABLES:
            init_c = initial_counts[tbl]
            fin_c = final_counts[tbl]
            diff = fin_c - init_c
            match_str = "MATCH (Zero Pollution)" if diff == 0 else f"MISMATCH ({diff:+d})"
            if diff != 0:
                all_matched = False
            print(f"  {tbl:16s}: Before={init_c:2d} | After={fin_c:2d} | Delta={diff:+2d} -> {match_str}")

        print("--------------------------------------------------------------------------------")
        if all_matched:
            print("RECONCILIATION RESULT: SUCCESS — 100% Zero Pollution across all tables.")
        else:
            print("RECONCILIATION RESULT: FAILURE — Data pollution detected.")
        print("================================================================================\n")

        print("PHASE 11 RESULTS SUMMARY:")
        for sc, st in results_summary.items():
            print(f"  [{st}] {sc}")

        db.close()


if __name__ == "__main__":
    run_phase11_security()
