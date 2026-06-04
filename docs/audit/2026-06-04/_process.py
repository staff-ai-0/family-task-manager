#!/usr/bin/env python3
"""Process workflow w00ab6eha output JSON -> audit markdown files."""
import json, sys, os

OUT = "/private/tmp/claude-501/-Volumes-shared-AgentIA-family-task-manager/34a578b4-2503-4a14-ae0b-253644f3a685/tasks/w00ab6eha.output"
DIR = "/Volumes/shared/AgentIA/family-task-manager/docs/audit/2026-06-04"

data = json.load(open(OUT))
data = data.get("result", data)  # workflow wraps payload under "result"
maps = data.get("map", [])
audited = data.get("audited", [])

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}

# ---- 01-map.md ----
with open(f"{DIR}/01-map.md", "w") as f:
    f.write("# Codebase Map (Phase 1 — 8 cluster explorers)\n\n")
    for m in maps:
        f.write(f"## {m.get('cluster','?')}\n\n{m.get('summary','')}\n\n")
        smells = m.get("debt_smells", [])
        if smells:
            f.write("**Debt smells:** " + "; ".join(smells) + "\n\n")
        for c in m.get("components", []):
            f.write(f"### {c.get('name','?')}\n")
            f.write(f"- Purpose: {c.get('purpose','')}\n")
            kf = c.get("key_files", [])
            if kf: f.write(f"- Files: {', '.join(kf)}\n")
            dbm = c.get("db_models", [])
            if dbm: f.write(f"- Models: {', '.join(dbm)}\n")
            eps = c.get("endpoints", [])
            if eps: f.write(f"- Endpoints: {len(eps)} (e.g. {'; '.join(eps[:4])})\n")
            if c.get("notes"): f.write(f"- Notes: {c['notes']}\n")
            f.write("\n")

# ---- helper: join verdicts to findings ----
def enrich(block):
    verds = {v.get("title",""): v for v in block.get("verdicts", [])}
    rows = []
    for fnd in block.get("findings", []):
        v = verds.get(fnd.get("title",""), {})
        rows.append({
            "dimension": block.get("dimension",""),
            "title": fnd.get("title",""),
            "category": fnd.get("category",""),
            "severity": fnd.get("severity","").lower(),
            "adj": (v.get("severity_adjusted") or fnd.get("severity","")).lower(),
            "real": v.get("real", None),
            "domain": fnd.get("domain",""),
            "evidence": fnd.get("evidence",""),
            "impact": fnd.get("impact",""),
            "fix": fnd.get("fix",""),
            "effort": fnd.get("effort",""),
            "reason": v.get("reason",""),
        })
    return rows

all_rows = []
for block in audited:
    all_rows.extend(enrich(block))

UX_DIMS = {"ux-budget", "ux-task", "ux-gig"}

def write_findings(path, title, rows, note=""):
    rows = sorted(rows, key=lambda r: (SEV_ORDER.get(r["adj"],9), r["dimension"]))
    with open(path, "w") as f:
        f.write(f"# {title}\n\n")
        if note: f.write(note + "\n\n")
        f.write(f"Total: {len(rows)} findings. "
                f"Confirmed-real: {sum(1 for r in rows if r['real'] is True)}, "
                f"refuted: {sum(1 for r in rows if r['real'] is False)}, "
                f"unverified: {sum(1 for r in rows if r['real'] is None)}.\n\n")
        cur = None
        for r in rows:
            if r["dimension"] != cur:
                cur = r["dimension"]; f.write(f"\n## [{cur}]\n\n")
            flag = "✅REAL" if r["real"] is True else ("❌REFUTED" if r["real"] is False else "·unverified")
            sevtxt = r["adj"].upper()
            if r["adj"] != r["severity"]: sevtxt += f" (was {r['severity'].upper()})"
            f.write(f"### [{sevtxt}] {r['title']}  — {flag}\n")
            f.write(f"- Domain: {r['domain']} · Category: {r['category']} · Effort: {r['effort']}\n")
            f.write(f"- Evidence: {r['evidence']}\n")
            f.write(f"- Impact: {r['impact']}\n")
            f.write(f"- Fix: {r['fix']}\n")
            if r["reason"]: f.write(f"- Verify: {r['reason']}\n")
            f.write("\n")

tech_rows = [r for r in all_rows if r["dimension"] not in UX_DIMS]
ux_rows   = [r for r in all_rows if r["dimension"] in UX_DIMS]

write_findings(f"{DIR}/02-techdebt.md", "Tech-Debt / Prod-Gap / Security Findings (Phase 2+3)",
               tech_rows, "Cross-cutting audit dimensions with adversarial verification.")
write_findings(f"{DIR}/04-ux-friction.md", "UX Friction — Budget / Task / Gigs (Phase 2+3)",
               ux_rows, "Goal: simplest possible workflows.")

# ---- 05 prioritized: confirmed-real (or unverified), critical+high first ----
prio = [r for r in all_rows if r["real"] is not False]
prio = sorted(prio, key=lambda r: (SEV_ORDER.get(r["adj"],9),))
with open(f"{DIR}/05-verified-prioritized.md", "w") as f:
    f.write("# Verified + Prioritized Backlog\n\n")
    f.write("Refuted findings dropped. Sorted by (verify-adjusted) severity.\n\n")
    for sev in ["critical","high","medium","low"]:
        bucket = [r for r in prio if r["adj"] == sev]
        if not bucket: continue
        f.write(f"\n## {sev.upper()} ({len(bucket)})\n\n")
        for i, r in enumerate(bucket, 1):
            flag = "" if r["real"] is True else " [UNVERIFIED]"
            f.write(f"{i}. **{r['title']}**{flag} `[{r['dimension']}/{r['domain']}]` (effort {r['effort']})\n")
            f.write(f"   - {r['evidence']}\n")
            f.write(f"   - Fix: {r['fix']}\n")

# ---- counts summary to stdout ----
print("CLUSTERS:", len(maps))
print("TOTAL findings:", len(all_rows))
from collections import Counter
print("by adj severity:", dict(Counter(r["adj"] for r in all_rows)))
print("real:", dict(Counter(str(r["real"]) for r in all_rows)))
print("by dimension:", dict(Counter(r["dimension"] for r in all_rows)))
print("\nCONFIRMED critical+high:")
for r in sorted([r for r in all_rows if r["real"] is True and r["adj"] in ("critical","high")],
                key=lambda r:(SEV_ORDER[r["adj"]],)):
    print(f"  [{r['adj'].upper()}] ({r['dimension']}) {r['title']}")
