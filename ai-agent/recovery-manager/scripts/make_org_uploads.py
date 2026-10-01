import csv
from pathlib import Path
import sys

source = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
org = sys.argv[3]
out_dir.mkdir(parents=True, exist_ok=True)
with source.open(newline='', encoding='utf-8') as f:
    rows = [r for r in csv.DictReader(f) if r.get('org_id') == org]
with (out_dir / f'{source.stem}_{org}.csv').open('w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(out_dir / f'{source.stem}_{org}.csv')
