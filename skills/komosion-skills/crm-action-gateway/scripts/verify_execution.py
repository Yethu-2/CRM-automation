#!/usr/bin/env python3
"""Verify an approval covers the exact payload about to be written.
approval.json: {proposal_id, decision, reviewer, approved_payload_sha256, executed(optional bool)}
payload.json: the payload to write. evaluation.json: {verdict}.
Exit 0 only if all checks pass.
"""
import argparse, json, hashlib, sys

def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

ap = argparse.ArgumentParser()
ap.add_argument("--approval", required=True)
ap.add_argument("--payload", required=True)
ap.add_argument("--evaluation", required=True)
a = ap.parse_args()
approval = json.load(open(a.approval)); payload = json.load(open(a.payload)); ev = json.load(open(a.evaluation))

checks = {
    "approval_decision": approval.get("decision") in ("approve", "edit"),
    "reviewer_present": bool((approval.get("reviewer") or "").strip()),
    "payload_matches_approval": approval.get("approved_payload_sha256") == sha(payload),
    "evaluator_not_blocked": ev.get("verdict") != "block",
    "not_already_executed": not approval.get("executed", False),
}
print(json.dumps({"checks": checks, "payload_sha256": sha(payload),
                  "allowed": all(checks.values())}, indent=2))
sys.exit(0 if all(checks.values()) else 1)
