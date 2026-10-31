---
name: human-review-capture
description: Records human review of an AI recommendation or assessment without overwriting the original, preserving original output, edited output, edit rationale, reviewer, timestamp, evidence references and agent version, so edits become reusable learning evidence. Use whenever a person approves, edits, rejects or defers an AI output, whenever feedback or corrections to an agent response are given, or when building the teacher or Action Learning layer, even if the user just says "I changed this" or "that recommendation was wrong".
---

# Human review capture

Human edits are the most valuable training signal in the system, but only if the original survives next to the correction. Overwriting destroys the lesson. Capture every review as a new record.

## Required fields

| Field | Purpose |
|---|---|
| `original_output` | Preserves the initial AI recommendation, untouched |
| `edited_output` | The human-corrected version (same as original if approved unchanged) |
| `decision` | approve / edit / reject / defer |
| `edit_rationale` | Why the change was made |
| `reviewer` | Who decided |
| `timestamp` | When (UTC, set by the system, not by you) |
| `evidence_references` | The evidence the output rested on |
| `agent_version` | Prompt/agent configuration that produced the original |

## Procedure

1. Receive the original output and the human's decision and edits.
2. If the decision is `edit` or `reject` and no rationale was given, ask the reviewer for one short sentence. If they decline, store the record with the rationale marked missing. Never invent a rationale; a guessed reason would teach future runs the wrong lesson.
3. Run `python scripts/build_review_record.py --original original.json --edited edited.json --decision edit --reviewer "<name>" --rationale "<text>" --agent-version "<version>"`. It writes the record, computes which fields changed, hashes the original, and flags whether the record is usable as a teacher example.
4. Store the record in the evidence store (append-only). Link it to the proposal it reviewed.
5. Pass `decision` and the edited output onward: only an `approve` or `edit` can lead to the `crm-action-gateway`.

## Using records later

Only records with a rationale are eligible as reviewed examples. Retrieve them as guidance for similar future cases (same business issue or situation type); they inform reasoning and never change numeric weights. Surface the rationale together with the corrected output so the agent learns why, not just what.
