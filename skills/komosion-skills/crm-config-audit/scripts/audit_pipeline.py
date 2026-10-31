#!/usr/bin/env python3
"""Deterministic CRM hygiene checks.
Input JSON:
{"as_of": "2026-10-04",
 "stages": [{"pipeline": "", "name": ""}],
 "stage_criteria_defined": ["stage name", ...],
 "custom_fields": [{"name": "", "fill_rate": 0.0-1.0}],
 "deals": [{"id": "", "title": "", "stage": "", "status": "open|won|lost",
            "next_activity_date": "YYYY-MM-DD or null", "last_activity_date": "YYYY-MM-DD or null"}],
 "native_automations": [{"name": "", "enabled": true, "trigger": "", "action": ""}]}
"""
import argparse, json, re, datetime, collections

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def d(s):
    return datetime.date.fromisoformat(s) if s else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--stale-days", type=int, default=30)
    ap.add_argument("--low-fill", type=float, default=0.1)
    a = ap.parse_args()
    x = json.load(open(a.path))
    as_of = d(x.get("as_of")) or datetime.date.today()
    f = {}
    defined = {norm(s) for s in x.get("stage_criteria_defined", [])}
    f["stages_without_criteria"] = [s["name"] for s in x.get("stages", []) if norm(s["name"]) not in defined]

    groups = collections.defaultdict(list)
    for c in x.get("custom_fields", []):
        groups[norm(c["name"])].append(c["name"])
    f["near_duplicate_fields"] = [v for v in groups.values() if len(v) > 1]
    f["rarely_filled_fields"] = [c["name"] for c in x.get("custom_fields", [])
                                 if c.get("fill_rate", 1) < a.low_fill]

    open_deals = [dl for dl in x.get("deals", []) if dl.get("status") == "open"]
    f["open_deals_without_next_activity"] = [dl["id"] for dl in open_deals if not dl.get("next_activity_date")]
    f["overdue_next_activity"] = [dl["id"] for dl in open_deals
                                  if dl.get("next_activity_date") and d(dl["next_activity_date"]) < as_of]
    stale = []
    for dl in open_deals:
        last = d(dl.get("last_activity_date"))
        if last is None or (as_of - last).days > a.stale_days:
            stale.append(dl["id"])
    f["stale_open_deals"] = stale
    enabled = [m for m in x.get("native_automations", []) if m.get("enabled")]
    f["enabled_automations_for_review"] = enabled
    trig = collections.Counter(m.get("trigger") for m in enabled)
    f["automations_sharing_trigger"] = [t for t, n in trig.items() if n > 1]
    f["summary"] = {"open_deals": len(open_deals), "enabled_automations": len(enabled)}
    print(json.dumps(f, indent=2))

if __name__ == "__main__":
    main()
