# Demo Runbook: Reproducible Reset & Demonstration Procedure

This runbook describes the exact step-by-step procedure to reset the database, upload source files, execute the recovery pipeline, and verify the expected outcomes for `org_demo_alpha` prior to recording or demoing.

---

## Prerequisites & Rules

- **Target Tenant**: `org_demo_alpha`
- **Protected Tenant**: `org_demo_bravo` (must remain untouched)
- **Constraint Compliance**:
  - Do NOT disable or modify Row-Level Security (RLS) policies.
  - Do NOT modify business logic or database schema.
  - Do NOT edit original sample CSV files.
  - The database uses `FORCE ROW LEVEL SECURITY`. Administrative/reset operations must explicitly set `app.current_org = 'org_demo_alpha'`.

---

## Step 1: Run `demo_reset.sql`

Reset the database to clean slate for `org_demo_alpha` while strictly preserving `org_demo_bravo`.

### Option A: Using `psql` (PostgreSQL CLI)

```bash
# From repository root or recovery-manager/
psql "postgresql://postgres:postgres@localhost:5432/recovery_db" -f scripts/demo_reset.sql
```

### Option B: Using Python / Backend Environment

```bash
cd recovery-manager
python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
s = SessionLocal()
with open('scripts/demo_reset.sql', 'r') as f:
    s.execute(text(f.read()))
s.commit()
s.close()
print('Demo reset complete.')
"
```

### What `demo_reset.sql` Does:
1. Temporarily bypasses the append-only immutability trigger on `overrides` (`trg_prevent_overrides_mutation`).
2. Deletes derived pipeline artifacts for `org_demo_alpha`: `reimbursements`, `claim_evidence`, `claims`, `assessment_log`, `pipeline_errors`.
3. Deletes overrides and ingestion records for `org_demo_alpha`: `overrides`, `charges`, `evidence`, `shipments`, `orders`.
4. Re-enables the `overrides` immutability trigger.
5. All operations run within an atomic transaction.

---

## Step 2: Upload Evidence Files (Exact Order)

Upload the 8 evidence files in the exact order specified below.

> **Note**: These files contain multi-tenant rows (`org_demo_alpha` and `org_demo_bravo`). When uploaded under `org_demo_alpha`, `IngestionService` safely ingests `org_demo_alpha` records and reports `TENANT_MISMATCH` for `org_demo_bravo` records (expected isolation behavior).

### Upload Order:
1. `data/receiving_sample.csv`
2. `data/prep_sample.csv`
3. `data/pack_sample.csv`
4. `data/returns_sample.csv`
5. `data/demo_extra_receiving.csv`
6. `data/demo_extra_prep.csv`
7. `data/demo_extra_pack.csv`
8. `data/demo_extra_returns.csv`

### Execution Command:
```bash
cd recovery-manager
python -c "
import asyncio
from app.core.database import SessionLocal
from app.services.ingestion import IngestionService

files = [
    'data/receiving_sample.csv',
    'data/prep_sample.csv',
    'data/pack_sample.csv',
    'data/returns_sample.csv',
    'data/demo_extra_receiving.csv',
    'data/demo_extra_prep.csv',
    'data/demo_extra_pack.csv',
    'data/demo_extra_returns.csv'
]

async def upload_evidence():
    db = SessionLocal()
    svc = IngestionService(db, 'org_demo_alpha')
    for fpath in files:
        with open(fpath, 'rb') as f:
            res = await svc.ingest_file(f, fpath.split('/')[-1])
            print(f'Uploaded {fpath}: inserted={res[\"rows_inserted\"]}, rejected={res[\"rows_rejected\"]}')
    db.close()

asyncio.run(upload_evidence())
"
```

Expected evidence inserted for `org_demo_alpha`: **155 rows** (Receiving: 67, Prep: 41, Pack: 20, Returns: 11, Demo Extra: 16).

---

## Step 3: Upload Charge Files

Upload the fee report and synthetic demonstration charges.

### Upload Order:
1. `data/fee_report_sample.csv`
2. `data/demo_extra_charges.csv`

### Execution Command:
```bash
cd recovery-manager
python -c "
import asyncio
from app.core.database import SessionLocal
from app.services.ingestion import IngestionService

files = [
    'data/fee_report_sample.csv',
    'data/demo_extra_charges.csv'
]

async def upload_charges():
    db = SessionLocal()
    svc = IngestionService(db, 'org_demo_alpha')
    for fpath in files:
        with open(fpath, 'rb') as f:
            res = await svc.ingest_file(f, fpath.split('/')[-1])
            print(f'Uploaded {fpath}: inserted={res[\"rows_inserted\"]}, rejected={res[\"rows_rejected\"]}')
    db.close()

asyncio.run(upload_charges())
"
```

Expected charges inserted for `org_demo_alpha`: **46 rows** (Fee report: 40, Demo Extra: 6).  
Expected rejections from `demo_extra_charges.csv`:
- **1 Duplicate**: Row 8 (`DEMO-CHG-001` duplicate)
- **1 Corrupt Amount**: Row 9 (`DEMO-CORRUPT-999`, invalid number `"INVALID_AMOUNT"`)
- **1 Unsupported Type**: Row 10 (`DEMO-CHG-UNSUPPORTED`, unconfigured charge type `"mystery_box_fee"`)

---

## Step 4: Run Recovery Pipeline

Trigger the recovery audit pipeline across all pending charges for `org_demo_alpha`.

### Via Backend CLI / Script:
```bash
cd recovery-manager
python -c "
import asyncio
from app.core.database import SessionLocal
from app.services.orchestrator import RecoveryOrchestrator

async def run_pipeline():
    db = SessionLocal()
    orch = RecoveryOrchestrator(db, 'org_demo_alpha')
    batch_res = await orch.run_batch()
    print(f'Batch complete: processed={batch_res[\"total_processed\"]}, succeeded={batch_res[\"succeeded\"]}, failed={batch_res[\"failed\"]}')
    db.close()

asyncio.run(run_pipeline())
"
```

### Via UI / Frontend:
- Open the dashboard at `http://localhost:5173/` (or running port).
- Select Active Tenant: **Alpha Logistics** (`org_demo_alpha`).
- Navigate to **Pipeline / Audit** and click **Run Recovery Audit**.

---

## Step 5: Expected Outcomes Table

| Metric / Scenario | Expected Count | Value / Notes |
| :--- | :---: | :--- |
| **Total Ingested Charges** | **46** | 42 evaluated fee charges + 4 inventory adjustments ($0.00) |
| **Total Claims Generated** | **8** | Status `READY_FOR_REVIEW`, Confidence `0.95` |
| **Total Claim Amount** | — | **$24.00** |
| **CONTRADICTED Count** | **8** | 5 from sample fees + 3 synthetic (`DEMO-CHG-001`, `002`, `006`) |
| **SUPPORTED Count** | **4** | 3 from sample fees + 1 synthetic (`DEMO-CHG-004`) |
| **SILENT Count** | **29** | 28 from sample fees + 1 synthetic (`DEMO-CHG-003`)* |
| **UNCERTAIN Count** | **1** | Flagged for human review (`DEMO-CHG-005`, $5.00) |
| **Rejected Duplicates** | **1** | `DEMO-CHG-001` duplicate row in `demo_extra_charges.csv` |
| **Rejected Corrupt Rows** | **1** | `DEMO-CORRUPT-999` with non-numeric amount |
| **Rejected Unsupported Types**| **1** | `DEMO-CHG-UNSUPPORTED` (`mystery_box_fee`) |

\* *Operational Notice on `DEMO-CHG-003`*: The LLM evaluation assesses `DEMO-CHG-003` ($18.00 `damaged_in_warehouse`) as `SILENT` due to warehouse receiving evidence not establishing carrier liability beyond ambiguity.

---

## Step 6: Verification

Execute `scripts/demo_verify.sql` to confirm all database counts:

```bash
# Using psql:
psql "postgresql://postgres:postgres@localhost:5432/recovery_db" -f scripts/demo_verify.sql
```
