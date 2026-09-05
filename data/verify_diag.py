import json, sys
sys.path.insert(0, '/app')
from app.eval.ground_truth import REPORTS
from app.mapping.mapper import map_report

ids = json.load(open('/data/eval_reports.json'))
targets = ['dfir-confluence-lockbit', 'dfir-rdp-ransomhub', 'dfir-bengalseo']

rows = []
for name in targets:
    gt = REPORTS[name]
    universe = set(gt.core) | set(gt.acceptable)
    mappings = map_report(ids[name], verify='demote', verdict='independent')
    for m in mappings:
        rows.append({
            'report': name, 'tid': m.technique_id, 'flagged': m.flagged,
            'in_table': m.technique_id in gt.core,
            'in_universe': m.technique_id in universe,
            'confidence': m.confidence, 'reason': m.reason[:80],
        })

flagged_in = sum(1 for r in rows if r['flagged'] and r['in_table'])
flagged_out = sum(1 for r in rows if r['flagged'] and not r['in_table'])
unflagged_in = sum(1 for r in rows if not r['flagged'] and r['in_table'])
unflagged_out = sum(1 for r in rows if not r['flagged'] and not r['in_table'])
print(f"flagged:   {flagged_in} in DFIR table / {flagged_out} not -> {flagged_in/(flagged_in+flagged_out):.1%} in table" if (flagged_in+flagged_out) else "no flagged")
print(f"unflagged: {unflagged_in} in DFIR table / {unflagged_out} not -> {unflagged_in/(unflagged_in+unflagged_out):.1%} in table" if (unflagged_in+unflagged_out) else "no unflagged")
print()
json.dump(rows, open('/data/verify_diag_rows.json', 'w'), indent=2)
print(f"wrote {len(rows)} rows to /data/verify_diag_rows.json")
