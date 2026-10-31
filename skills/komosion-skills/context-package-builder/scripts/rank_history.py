#!/usr/bin/env python3
"""Apply Komosion historical-context selection rules and rank deterministically.

Input: JSON list of candidates, each with:
  id, occurred_at (ISO string), relationship_to_current, rules {rule_name: bool}
Rule: include only if >=1 rule matches AND relationship_to_current is non-empty.
Rank: most rules matched, then direct_relationship, then recency (tiebreaker only).
"""
import argparse, json

RULES = ["same_business_issue", "same_opportunity", "same_stakeholder",
         "direct_relationship", "previous_decision_impact", "previous_outcome_relevance"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--max", type=int, default=5)
    a = ap.parse_args()
    cands = json.load(open(a.path))
    kept, excluded = [], []
    for c in cands:
        c["matched_rules"] = [r for r in RULES if c.get("rules", {}).get(r)]
        if not c["matched_rules"]:
            c["exclusion_reason"] = "no selection rule matched"
            excluded.append(c)
        elif not (c.get("relationship_to_current") or "").strip():
            c["exclusion_reason"] = "missing relationship_to_current"
            excluded.append(c)
        else:
            kept.append(c)
    # stable sorts: recency first (tiebreak), then relevance dominates
    kept.sort(key=lambda c: c.get("occurred_at", ""), reverse=True)
    kept.sort(key=lambda c: (len(c["matched_rules"]),
                             1 if "direct_relationship" in c["matched_rules"] else 0),
              reverse=True)
    out = {"selected": kept[:a.max], "overflow": kept[a.max:], "excluded": excluded}
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
