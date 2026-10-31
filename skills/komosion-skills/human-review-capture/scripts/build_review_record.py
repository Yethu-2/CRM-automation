#!/usr/bin/env python3
"""Build an append-only human review record. Never mutates the original."""
import argparse, json, hashlib, datetime

def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", required=True)
    ap.add_argument("--edited", required=True)
    ap.add_argument("--decision", required=True, choices=["approve", "edit", "reject", "defer"])
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--rationale", default="")
    ap.add_argument("--agent-version", default="")
    a = ap.parse_args()
    orig = json.load(open(a.original)); edited = json.load(open(a.edited))
    changed = sorted(k for k in set(orig) | set(edited) if orig.get(k) != edited.get(k))
    needs_rationale = a.decision in ("edit", "reject")
    rationale_missing = needs_rationale and not a.rationale.strip()
    refs = orig.get("evidence_references", {})
    rec = {
        "original_output": orig,
        "original_sha256": sha(orig),
        "edited_output": edited,
        "changed_fields": changed,
        "decision": a.decision,
        "edit_rationale": a.rationale.strip() or None,
        "rationale_missing": rationale_missing,
        "reviewer": a.reviewer,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "evidence_references": refs,
        "agent_version": a.agent_version or orig.get("agent_version", ""),
        "usable_as_teacher_example": (a.decision in ("edit", "reject", "approve")) and not rationale_missing
                                     and bool(a.agent_version or orig.get("agent_version")),
    }
    if a.decision == "edit" and not changed:
        rec["warning"] = "decision is edit but edited output equals original"
    print(json.dumps(rec, indent=2))

if __name__ == "__main__":
    main()
