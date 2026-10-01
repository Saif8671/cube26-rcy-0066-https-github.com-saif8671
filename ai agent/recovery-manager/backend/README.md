
# Recovery Manager - Backend Service

This is the backend foundation for **Recovery Manager**, built with **FastAPI** and **SQLAlchemy** (targeting PostgreSQL / Supabase).

## Directory Structure

```text
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application factory & entrypoint
│   ├── api/                    # API routers and versioned endpoints
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       └── health.py       # Health check endpoint (/health)
│   ├── core/                   # Application configuration, DB engine, logging, error handling
│   │   ├── __init__.py
│   │   ├── config.py           # Typed environment settings (Pydantic)
│   │   ├── database.py         # SQLAlchemy engine, sessionmaker, get_db dependency
│   │   ├── logging.py          # Structured logging configuration (sanitizes secrets)
│   │   └── errors.py           # Centralized HTTP & database exception handlers
│   ├── models/                 # SQLAlchemy ORM models mirroring Phase 1 PostgreSQL schema
│   │   ├── __init__.py
│   │   ├── shipment.py
│   │   ├── order.py
│   │   ├── charge.py
│   │   ├── evidence.py
│   │   ├── reimbursement.py
│   │   ├── claim.py
│   │   └── claim_evidence.py
│   ├── schemas/                # Pydantic validation & response schemas
│   │   ├── __init__.py
│   │   └── health.py
│   └── services/               # Foundation service namespace (reserved for future phases)
│       └── __init__.py
├── requirements.txt
├── .env.example
└── README.md
```

## Running the Application

From the `backend` directory:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run with Uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Health Verification

```bash
curl http://localhost:8000/health
```

Expected JSON response:
```json
{
  "status": "ok",
  "database": "connected",
  "version": "0.1.0",
  "environment": "development"
}
```
