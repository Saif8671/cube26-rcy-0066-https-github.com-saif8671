# Recovery Manager Demo Walkthrough

A complete, step-by-step verification and demonstration guide for **Recovery Manager (Pod 5 of 5)**.

This walkthrough covers both the **Web Interface (Next.js at `http://localhost:3000`)** and the **REST API (FastAPI at `http://localhost:8000`)**.

---

## Prerequisites & Environment

Ensure both services are active:
- **Backend API:** `http://localhost:8000` (FastAPI + SQLAlchemy)
- **Frontend Console:** `http://localhost:3000` (Next.js App Router)
- **Database:** PostgreSQL / Supabase with migrations applied up to `004_overrides_and_fail_open.sql`
- **Default Organization Header:** `X-Org-Id: org_demo_alpha`

---

## Step 1: Upload Real Fee Report

Ingest an authentic marketplace fee report into the system.

### Via Web Interface
1. Open your browser and navigate to `http://localhost:3000/upload`.
2. Ensure the active tab is **"Marketplace Charges"**.
3. Select or drag-and-drop [`data/fee_report_sample.csv`](file:///e:/saif/projects%20made/codequest/ai%20agent/recovery-manager/data/fee_report_sample.csv) (or [`test_upload_charges.csv`](file:///e:/saif/projects%20made/codequest/ai%20agent/recovery-manager/test_upload_charges.csv)).
4. Click **"Upload & Ingest"**.

### Via cURL / Terminal
```bash
curl -X POST "http://localhost:8000/api/v1/ingestion/charges" \
  -H "X-Org-Id: org_demo_alpha" \
  -F "file=@data/fee_report_sample.csv"
```

### Verification & Expected Result
The system streams the file (under a 10 MB DoS protection limit), extracts line records, and returns HTTP 200 with an ingestion summary:
```json
{
  "status": "success",
  "source_report": "fee_report_sample.csv",
  "total_records": 62,
  "successful_ingestions": 62,
  "failed_ingestions": 0,
  "created_shipments": 4,
  "created_orders": 8,
  "errors": []
}
```
All charges are persisted with `status='PENDING'`, and the raw marketplace attributes are preserved in `charges.raw_data` for auditability.

---

## Step 2: Run Recovery Pipeline & Evidence Retrieval

Trigger the synchronous 7-stage evaluation pipeline to resolve entities and retrieve operational proofs from upstream warehouse managers.

### Via Web Interface
1. Navigate to `http://localhost:3000/charges`.
2. Click on any `PENDING` charge (e.g. `CHG-FBA-8902` or `FEE-0002-1`).
3. Click the blue **"Run Recovery Pipeline"** button in the header.

### Via cURL / Terminal
```bash
curl -X POST "http://localhost:8000/api/v1/pipeline/process/CHG-FBA-8902" \
  -H "X-Org-Id: org_demo_alpha" \
  -H "Content-Type: application/json"
```

### Verification & Evidence Hierarchy
The pipeline immediately executes:
1. **Entity Resolution:** Resolves `unit_id`, `fnsku`, `sku`, `shipment_id`, and `order_id`.
2. **Evidence Engine:** Queries operational records across Pods 1–4 using the deterministic join hierarchy:
   $$\mathbf{unit\_id} \;\longrightarrow\; \mathbf{fnsku} \;\longrightarrow\; \mathbf{sku} \;\longrightarrow\; \mathbf{shipment\_id} \;\longrightarrow\; \mathbf{order\_id} \;\longrightarrow\; \mathbf{asin}$$
3. The response returns synchronously with the matched evidence count and IDs:
```json
{
  "outcome": "CLAIM_CREATED",
  "charge_id": "CHG-FBA-8902",
  "claim_id": "CLM-4F2A109B",
  "status": "READY_FOR_REVIEW",
  "assessment": "CONTRADICTED",
  "claim_amount": 45.50,
  "confidence": 0.96,
  "reason": "Receiving weight scan verifies shipment weight was 0.45 kg, contradicting 1.20 kg billed.",
  "evidence_count": 1,
  "evidence_ids": ["EVD-REC-8902"]
}
```

---

## Step 3: Inspect a CONTRADICTED Charge (Claim Created)

When operational evidence refutes the marketplace charge, the seller is not at fault.

### Flow
1. In the UI, navigate to `http://localhost:3000/charges/CHG-FBA-8902` (or navigate to `http://localhost:3000/claims`).
2. Observe the three core sections:
   - **Operational Evidence Provenance:** Shows the exact inspection record from **Receiving Manager** (`EVD-REC-8902`) with station timestamp, certified scale tare weight (`0.45 kg`), and photo links.
   - **AI Reasoning Output:** Displays Gemini's plain-English explanation:  
     *"Receiving weight scan verifies shipment weight was 0.45 kg, directly contradicting the 1.20 kg billed tier."*
   - **Generated Claim:** A formal claim record `CLM-4F2A109B` has been generated for **$45.50** with status **`READY_FOR_REVIEW`**.
3. Notice that `claim_evidence` junction rows link the claim directly to `EVD-REC-8902` for defense auditability.

---

## Step 4: Inspect a SILENT Charge (No Frivolous Claim)

Demonstrate adherence to the rule: **"Evidence first, claim second."**

### Flow
1. Navigate to a charge where no upstream warehouse evidence exists (e.g., `CHG-FBA-8903` or `FEE-0005-1`):
   `http://localhost:3000/charges/CHG-FBA-8903`
2. Click **"Run Recovery Pipeline"** (or execute `curl -X POST "http://localhost:8000/api/v1/pipeline/process/CHG-FBA-8903" -H "X-Org-Id: org_demo_alpha"`).
3. Observe the result:
   - **Pipeline Outcome:** `NO_CLAIM`
   - **Assessment Classification:** `SILENT`
   - **Reason:** *"No operational evidence found in Receiving, Prep, Pack, or Returns for this unit/shipment."*
4. **Why no claim is created:**  
   Unlike speculative audit bots that file blind disputes, Recovery Manager refuses to invent evidence. The evaluation is recorded in `assessment_log` for complete auditability, but **no claim row is created**, protecting merchant credibility with carriers.

---

## Step 5: Inspect an UNCERTAIN Charge (Pending Review Queue)

Demonstrate adherence to Engineering Rule 4: **"Uncertain is a valid verdict."**

### Flow
1. When operational records contain contradictory findings (for example, Pack station logs indicate an item was undamaged and sealed, but dock receipt logs note packaging damage), the model classifies the charge as `UNCERTAIN`.
2. In the UI, navigate to `http://localhost:3000/charges/pending-review`.
3. Locate `CHG-FBA-8904`.
4. Observe:
   - The charge has an `UNCERTAIN` assessment banner with a status of `pending_review`.
   - No claim row is created automatically.
   - Both contradictory evidence records are displayed side-by-side with full timestamps, awaiting supervisor inspection.

---

## Step 6: Apply Human Supervisor Override

Demonstrate adherence to the rule: **"Overrides are data."**

### Flow
1. On the charge detail page or pending review queue for `CHG-FBA-8904`, click the **"Supervisor Override"** button.
2. In the modal, select:
   - **New Verdict:** `CONTRADICTED` (or `REJECTED`)
   - **Operator ID:** `supervisor_lead_01`
   - **Operational Reason:** *"Manual station inspection confirmed packing polybag met mil thickness requirements; photo artifact corroborated compliance."*
3. Submit the override (or invoke via cURL):
   ```bash
   curl -X POST "http://localhost:8000/api/v1/charges/CHG-FBA-8904/override" \
     -H "X-Org-Id: org_demo_alpha" \
     -H "Content-Type: application/json" \
     -d '{
       "new_verdict": "CONTRADICTED",
       "reason": "Manual station inspection confirmed packing polybag met mil thickness requirements.",
       "reviewer_id": "supervisor_lead_01"
     }'
   ```
4. Observe the resulting state:
   - A recovery claim is created/updated to `READY_FOR_REVIEW` for the charge amount.
   - An immutable audit row is appended into the `overrides` table.
   - The PostgreSQL trigger `trg_prevent_overrides_mutation` ensures this record can never be modified or deleted.
   - The original AI evaluation remains intact in `assessment_log`.

---

## Step 7: Open Dashboard & Review Operational Metrics

Inspect real-time aggregated metrics computed directly from PostgreSQL.

### Flow
1. Navigate to `http://localhost:3000/dashboard` (or `GET /api/v1/dashboard/metrics`).
2. Review the KPI cards:
   - **Total Charges:** Count of all ingested fee records.
   - **Total Potential Recovery:** Cumulative dollar sum of claims in `READY_FOR_REVIEW` with `CONTRADICTED` assessment.
   - **Evaluations by Assessment:** Bar/donut breakdown of `CONTRADICTED`, `SUPPORTED`, `SILENT`, and `UNCERTAIN` outcomes.
   - **Claims by Lifecycle Status:** Real-time tally of `READY_FOR_REVIEW`, `APPROVED`, `REJECTED`, `DUPLICATE`, and `ALREADY_REIMBURSED`.
   - **Unprocessed vs Processed Without Claim:** Work backlog indicators.

> [!NOTE]
> **Important Note on AI Metrics:**  
> **Human overrides are excluded from AI assessment metrics.**  
> The dashboard assessment metrics reflect purely automated AI evaluations where `confidence IS NOT NULL` from `assessment_log`. Human overrides are tracked in their own dedicated audit stream to prevent artificial inflation of AI accuracy numbers.

---

## Step 8: Multi-Tenancy Row-Level Security Isolation

Demonstrate strict cross-organization tenant isolation between `org_demo_alpha` and `org_demo_bravo`.

### Verification via Script
Execute the dedicated authenticated RLS verification script:
```bash
python verify_rls_isolation.py
```

### Manual Verification via cURL
1. Query charges visible to **Organization Alpha**:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/charges?limit=5" \
     -H "X-Org-Id: org_demo_alpha"
   ```
   *Result:* Returns only charges belonging to `org_demo_alpha`.

2. Query charges visible to **Organization Bravo**:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/charges?limit=5" \
     -H "X-Org-Id: org_demo_bravo"
   ```
   *Result:* Returns only charges belonging to `org_demo_bravo`. Zero Alpha charges appear.

3. **Direct Fetch-by-UUID Attack Test:**
   Attempt to fetch an `org_demo_bravo` charge UUID using an `org_demo_alpha` header:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/charges/<BRAVO_UUID>" \
     -H "X-Org-Id: org_demo_alpha"
   ```
   *Result:* HTTP 404 Not Found. The database kernel completely filters the row out, preventing cross-tenant leakage even when guessing exact primary keys.
