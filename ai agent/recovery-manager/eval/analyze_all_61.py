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

out_lines = []
for i, f in enumerate(fees, 1):
    u = f["unit_id"]
    cid = f["line_id"]
    ctype = f["charge_type"]
    amt = f["amount_usd"]
    rtype = f["report_type"]
    qty = f["quantity"]
    
    r = rcv.get(u)
    p = prp.get(u)
    pk = pck.get(u)
    rt = rtn.get(u)
    
    r_id = r["record_id"] if r else "-"
    p_id = p["record_id"] if p else "-"
    pk_id = pk["record_id"] if pk else "-"
    rt_id = rt["record_id"] if rt else "-"
    
    out_lines.append(f"[{i:02d}] {cid:12} | {u:10} | {rtype:20} | {ctype:32} | ${amt:5} | qty={qty}")
    if r:
        out_lines.append(f"     RCV {r_id}: match={r['identity_match']}, c_dmg={r['carton_damage']}, u_dmg={r['unit_damage']}, qf={r['quality_flags']}, rcvd={r['qty_received']}/{r['qty_ordered']}")
    if p:
        out_lines.append(f"     PRP {p_id}: poly(req={p['wo_polybag']}, obs={p['polybag_present_sealed']}), suff(req={p['wo_suffocation_warning']}, obs={p['suffocation_warning']}), fnsku={p['fnsku_label_placement']}, orig_cov={p['original_barcode_covered']}, hnd(req={p['wo_handling_marks']}, obs={p['handling_marks']}), exp(req={p['wo_expiry_date']}, obs={p['expiry_date']})")
    if pk:
        out_lines.append(f"     PCK {pk_id}: verdict={pk['operator_verdict']}, obs={pk['observed_in_box']}")
    if rt:
        out_lines.append(f"     RTN {rt_id}: state={rt['observed_state']}, disp={rt['operator_disposition']}, miss={rt['parts_missing']}, cond={rt['amazon_condition']}")

Path("eval/analysis_61_output.txt").write_text("\n".join(out_lines), encoding="utf-8")
print(f"Wrote {len(out_lines)} lines to eval/analysis_61_output.txt")
