#!/usr/bin/env python3
"""Mechanical validation of a Decision Governance response.
Usage: validate_response.py response.json context_package.json
Exit code 1 if any check fails. Prints JSON.
"""
import json, sys

REQUIRED = ["current_situation", "relevant_evidence", "relevant_historical_context",
            "interpretation", "information_gaps", "recommended_options",
            "primary_recommendation", "confidence", "evidence_references",
            "advisory", "agent_version"]

def collect_ids(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "id" and isinstance(v, str):
                out.add(v)
            collect_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_ids(v, out)

def main():
    resp = json.load(open(sys.argv[1]))
    pkg = json.load(open(sys.argv[2]))
    known = set(); collect_ids(pkg, known)
    checks = {}
    def rec(name, ok, detail=""):
        checks[name] = {"pass": bool(ok), "detail": detail}

    missing = [k for k in REQUIRED if k not in resp]
    rec("sections_present", not missing, f"missing: {missing}" if missing else "")

    refs = set()
    cs = resp.get("current_situation", {})
    refs.update(cs.get("refs", []) if isinstance(cs, dict) else [])
    for e in resp.get("relevant_evidence", []):
        refs.update(e.get("refs", []))
    for h in resp.get("relevant_historical_context", []):
        refs.update(h.get("refs", []))
    for i in resp.get("interpretation", []):
        refs.update(i.get("based_on", []))
    for o in resp.get("recommended_options", []):
        refs.update(o.get("refs", []))
    er = resp.get("evidence_references", {})
    if isinstance(er, dict):
        for v in er.values():
            refs.update(v)
    unresolved = sorted(r for r in refs if r not in known)
    rec("references_resolve", refs and not unresolved,
        f"unresolved: {unresolved}" if unresolved else ("no references" if not refs else ""))

    facts_bad = [e.get("statement", "")[:60] for e in resp.get("relevant_evidence", [])
                 if e.get("type") != "fact" or not e.get("refs")]
    rec("facts_cite_evidence", not facts_bad, f"facts without type/refs: {facts_bad}" if facts_bad else "")

    inf_bad = [i.get("statement", "")[:60] for i in resp.get("interpretation", [])
               if i.get("type") != "inference" or not i.get("based_on")]
    rec("inferences_labelled_and_grounded", not inf_bad, f"bad: {inf_bad}" if inf_bad else "")

    conf = resp.get("confidence", {})
    rec("confidence_valid", conf.get("level") in ("High", "Medium", "Low")
        and bool((conf.get("justification") or "").strip()),
        "needs level High/Medium/Low and a justification")

    gaps = resp.get("information_gaps", [])
    gaps_ok = (len(gaps) > 0 and all(g.get("gap") and g.get("impact") for g in gaps)) \
        or (len(gaps) == 0 and (resp.get("no_gaps_justification") or "").strip())
    rec("information_gaps_explicit", gaps_ok, "empty gaps need no_gaps_justification")

    opts = resp.get("recommended_options", [])
    rec("options_have_rationale", len(opts) >= 1 and all((o.get("rationale") or "").strip() for o in opts))
    rec("multiple_options", len(opts) >= 2, "advisory: preferably 2+ options, or justify")
    pr = resp.get("primary_recommendation", {})
    rec("primary_matches_option", pr.get("option_id") in {o.get("id") for o in opts})
    rec("advisory_flag", resp.get("advisory") is True)

    soft = {"multiple_options"}
    failed = [k for k, v in checks.items() if not v["pass"]]
    hard_failed = [k for k in failed if k not in soft]
    print(json.dumps({"checks": checks, "failed": failed, "hard_failed": hard_failed}, indent=2))
    sys.exit(1 if hard_failed else 0)

if __name__ == "__main__":
    main()
