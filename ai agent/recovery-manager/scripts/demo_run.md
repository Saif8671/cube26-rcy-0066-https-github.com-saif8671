# Demo run commands

Run these in PowerShell from `E:\saif\projects made\codequest\ai agent\recovery-manager`. Set the org header consistently; these commands do not run SQL or modify labels.

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In a second PowerShell window:

```powershell
$base = 'http://localhost:8000'
$org = 'org_demo_alpha'

curl.exe --fail-with-body --max-time 600 -X POST "$base/ingestion/evidence/receiving" -H "X-Org-Id: $org" -F "file=@E:\saif\projects made\codequest\ai agent\recovery-manager\data\upstream\receiving_sample.csv"
curl.exe --fail-with-body --max-time 600 -X POST "$base/ingestion/evidence/prep" -H "X-Org-Id: $org" -F "file=@E:\saif\projects made\codequest\ai agent\recovery-manager\data\upstream\prep_sample.csv"
curl.exe --fail-with-body --max-time 600 -X POST "$base/ingestion/evidence/returns" -H "X-Org-Id: $org" -F "file=@E:\saif\projects made\codequest\ai agent\recovery-manager\data\upstream\returns_sample.csv"
curl.exe --fail-with-body --max-time 600 -X POST "$base/ingestion/charges" -H "X-Org-Id: $org" -F "file=@E:\saif\projects made\codequest\ai agent\recovery-manager\data\fee_report_sample.csv"

curl.exe --fail-with-body --max-time 600 -X POST "$base/recovery/run" -H "X-Org-Id: $org"
curl.exe --fail-with-body --max-time 600 "$base/recovery/preview" -H "X-Org-Id: $org"
```

Optional read-only connection check (from the same directory):

```powershell
$env:PYTHONPATH = (Get-Location).Path
..\.venv\Scripts\python.exe scripts\db_connection_state.py
```
