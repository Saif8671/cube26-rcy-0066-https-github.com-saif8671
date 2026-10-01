import csv
from pathlib import Path

fee_path = Path("data/fee_report_sample.csv")
rcv_path = Path("data/upstream/receiving_sample.csv")
prp_path = Path("data/upstream/prep_sample.csv")
pck_path = Path("data/upstream/pack_sample.csv")
rtn_path = Path("data/upstream/returns_sample.csv")

with open(fee_path, encoding="utf-8") as f:
    fees = list(csv.DictReader(f))

with open(rcv_path, encoding="utf-8") as f:
    rcv = {r["unit_id"]: r for r in csv.DictReader(f)}

with open(prp_path, encoding="utf-8") as f:
    prp = {r["unit_id"]: r for r in csv.DictReader(f)}

with open(pck_path, encoding="utf-8") as f:
    pck = {r["unit_id"]: r for r in csv.DictReader(f)}

with open(rtn_path, encoding="utf-8") as f:
    rtn = {r["unit_id"]: r for r in csv.DictReader(f)}

print(f"Loaded {len(fees)} charges from fee_report_sample.csv")

for f in fees:
    cid = f["line_id"]
    u = f["unit_id"]
    ctype = f["charge_type"]
    amt = f["amount_usd"]
    rtype = f["report_type"]
    
    r = rcv.get(u)
    p = prp.get(u)
    pk = pck.get(u)
    rt = rtn.get(u)
    
    details = []
    if r:
        details.append(f"RCV: id_match={r.get('identity_match')}, c_dmg={r.get('carton_damage')}, u_dmg={r.get('unit_damage')}, qf={r.get('quality_flags')}")
    if p:
        details.append(f"PRP: poly_req={p.get('wo_polybag')}, poly_obs={p.get('polybag_present_sealed')}, suff_req={p.get('wo_suffocation_warning')}, suff_obs={p.get('suffocation_warning')}, fnsku_pos={p.get('fnsku_label_placement')}, orig_cov={p.get('original_barcode_covered')}, hnd_req={p.get('wo_handling_marks')}, hnd_obs={p.get('handling_marks')}")
    if pk:
        details.append(f"PCK: verdict={pk.get('operator_verdict')}")
    if rt:
        details.append(f"RTN: state={rt.get('observed_state')}, disp={rt.get('operator_disposition')}, missing={rt.get('parts_missing')}")
        
    line = f"{cid:12} | {u:10} | {ctype:32} | ${amt:6} | {rtype:20} -> " + (" || ".join(details) if details else "NO UPSTREAM")
    print(line)
