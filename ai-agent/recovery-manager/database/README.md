# Database Migrations & Setup Guide

This directory manages the PostgreSQL schema and verification seed data for **Recovery Manager**.

```
database/
├── migrations/
│   └── 001_initial_schema.sql     # Core initial migration
├── seed/
│   └── seed_traceable_example.sql # 3-4 row per table verifiable end-to-end dataset
├── schema.md                      # Detailed schema specs and Mermaid ER diagram
└── README.md                      # Instructions (this file)
```

---

## 1. Running Migrations Against a Local PostgreSQL Instance

### Prerequisites
- PostgreSQL 14+ installed and running locally, or running via Docker.
- A target database created (e.g., `recovery_manager`).

### Option A: Using `psql` Command Line
Ensure `psql` is in your `PATH`, then run:

```bash
# Connect and execute the initial schema migration
psql -h localhost -p 5432 -U postgres -d recovery_manager -f database/migrations/001_initial_schema.sql

# (Optional) Seed the database with traceable verification data
psql -h localhost -p 5432 -U postgres -d recovery_manager -f database/seed/seed_traceable_example.sql
```

### Option B: Running Local PostgreSQL in Docker
If you do not have PostgreSQL installed locally on your host machine:

```bash
# 1. Start a local Postgres 16 container
docker run --name recovery-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=recovery_manager -p 5432:5432 -d postgres:16-alpine

# 2. Run the migration inside the container
docker exec -i recovery-postgres psql -U postgres -d recovery_manager < database/migrations/001_initial_schema.sql

# 3. Apply the seed data
docker exec -i recovery-postgres psql -U postgres -d recovery_manager < database/seed/seed_traceable_example.sql
```

### Option C: Using Python
If `psql` is not installed on your system, you can execute the migration using Python:

```bash
python -c "
import psycopg2
conn = psycopg2.connect('postgresql://postgres:postgres@localhost:5432/recovery_manager')
with open('database/migrations/001_initial_schema.sql', 'r') as f:
    sql = f.read()
with conn.cursor() as cur:
    cur.execute(sql)
conn.commit()
conn.close()
print('Migration 001 applied successfully.')
"
```

---

## 2. Running Migrations Against Supabase

### Option A: Supabase Dashboard (Recommended for Quick Setup)
1. Log into your [Supabase Dashboard](https://supabase.com/dashboard).
2. Open your project and navigate to the **SQL Editor** in the left sidebar.
3. Click **New query**.
4. Open [001_initial_schema.sql](file:///database/migrations/001_initial_schema.sql), copy its contents, paste them into the SQL Editor, and click **Run**.
5. (Optional) Repeat the process with [seed_traceable_example.sql](file:///database/seed/seed_traceable_example.sql) to populate verification data.

### Option B: Direct Connection via `psql`
1. In your Supabase Dashboard, navigate to **Project Settings** -> **Database**.
2. Copy the **Connection string** (URI mode), which looks like:
   `postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres`
3. Execute the migration:

```bash
psql "postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres" -f database/migrations/001_initial_schema.sql
psql "postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres" -f database/seed/seed_traceable_example.sql
```

### Option C: Using Supabase CLI
If using the Supabase CLI workflow:

```bash
# Link your local project to your remote Supabase project
supabase link --project-ref [YOUR-PROJECT-REF]

# Push migrations to remote database
supabase db push
```

---

## 3. Verifying the Migration

After running the migration, verify the tables and indexes:

```sql
-- Check that all 7 core tables exist
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_name IN ('shipments', 'orders', 'charges', 'evidence', 'reimbursements', 'claims', 'claim_evidence');

-- Verify foreign keys and cascade rules
SELECT
    tc.table_name, 
    kcu.column_name, 
    ccu.table_name AS foreign_table_name,
    rc.delete_rule
FROM information_schema.table_constraints AS tc 
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.referential_constraints AS rc
  ON tc.constraint_name = rc.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON rc.unique_constraint_name = ccu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public';

-- Verify assessment check constraint
SELECT conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'public' AND conname LIKE '%assessment%';

-- Test end-to-end traceability query
SELECT 
    c.claim_id,
    c.assessment,
    c.claim_amount,
    c.confidence,
    ch.charge_id,
    ch.charge_type,
    ch.amount AS fee_amount,
    s.shipment_id,
    e.evidence_id,
    e.source_manager,
    e.evidence_type
FROM claims c
JOIN charges ch ON c.charge_id = ch.id
LEFT JOIN shipments s ON ch.shipment_id = s.id
JOIN claim_evidence ce ON c.id = ce.claim_id
JOIN evidence e ON ce.evidence_id = e.id;
```
