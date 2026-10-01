import urllib.request
import json
import uuid

def execute():
    # 1. Post CSV to /ingestion/charges
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    with open('test_upload_charges.csv', 'rb') as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test_upload_charges.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode('utf-8') + file_bytes + f"\r\n--{boundary}--\r\n".encode('utf-8')

    req = urllib.request.Request(
        'http://localhost:8000/ingestion/charges',
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST'
    )
    
    with urllib.request.urlopen(req) as resp:
        ingest_res = json.loads(resp.read().decode('utf-8'))

    print('=== INGESTION RESPONSE (POST /ingestion/charges) ===')
    print(json.dumps(ingest_res, indent=2))

    inserted_ids = ingest_res.get('inserted_ids', [])
    print(f"\nExtracted inserted_ids: {inserted_ids}")

    # 2. Simulate clicking "Process Uploaded Charges" -> POST /pipeline/process-batch
    batch_payload = json.dumps({'charge_ids': inserted_ids}).encode('utf-8')
    batch_req = urllib.request.Request(
        'http://localhost:8000/pipeline/process-batch',
        data=batch_payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    with urllib.request.urlopen(batch_req) as resp:
        batch_res = json.loads(resp.read().decode('utf-8'))

    print('\n=== BATCH PIPELINE RESPONSE (POST /pipeline/process-batch) ===')
    print(json.dumps(batch_res, indent=2))

if __name__ == '__main__':
    execute()
