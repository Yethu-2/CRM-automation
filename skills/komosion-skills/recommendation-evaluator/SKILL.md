---
name: recommendation-evaluator
description: Quality gate that checks an agent's recommendation before it reaches the human gate. Runs nine structured pass/fail checks (evidence, historical context, unsupported claims, fact vs inference, information gaps, recommendation, rationale, confidence, human authority) and the twelve acceptance criteria, and returns proceed, revise or block. Use whenever an agent response, recommendation, assessment or proposed CRM action needs verifying, grading or reviewing, or before anything is shown to a human reviewer, even if the user only says "check this" or "is this good enough to send for review".
---

# Recommendation evaluator

A recommendation that sounds reasonable is not enough. It must be evidence-grounded, context-aware, traceable, appropriately uncertain, commercially useful and safe for human review. Use structured checks, never a single aggregate score: a score can hide one fatal flaw behind many small wins.

Inputs: the agent response (see `decision-governance/references/output-contract.md`) and the context package it was built from.

## Step 1: mechanical checks (script)

Run `python scripts/validate_response.py response.json context_package.json`. It verifies structure, that every reference resolves to an ID in the package, facts cite evidence, inferences cite their basis, confidence is valid and justified, options and rationale exist, gaps are present, and `advisory` is true.

## Step 2: judgment checks (you)

Read the response against the package and record pass/fail with a one-line note for each:

| Check | Pass condition |
|---|---|
| Evidence | Supporting evidence exists for the recommendation |
| Historical context | Relevant history is used where applicable, and irrelevant history is absent |
| Unsupported claims | Nothing factual is stated without evidence |
| Fact vs inference | Clearly separated, with no inference worded as fact |
| Information gaps | Important unknowns are explicit, not silently filled |
| Recommendation | Actionable and commercially relevant |
| Rationale | Explains why each option is appropriate |
| Confidence | Provided and justified by the evidence |
| Human authority | Advisory until reviewed |

Look hardest for claims about feelings, intent, or commitments that the evidence does not state. These slip through most often.

## Step 3: verdict

- **block**: any failure in evidence grounding, traceability or human control. Do not let it progress; report why.
- **revise**: other failures. Return the specific failed checks to the agent for one revision, then re-evaluate. If it still fails, send to the human with the failures flagged.
- **proceed_to_human_gate**: all checks pass. This only means it may go to a human; it never authorises a CRM action.

## Acceptance criteria (all twelve must hold to proceed)

1. Current signal correctly represented
2. Relevant evidence identified
3. Historical context relevant to the signal
4. Facts and interpretations separated
5. No unsupported assumptions presented as facts
6. Important information gaps identified
7. Commercially relevant recommendation
8. Clear rationale
9. Confidence appropriate to evidence
10. Evidence and history traceable
11. Human review precedes any operational action
12. Human edits can be preserved for learning (the response carries the fields `human-review-capture` needs: agent version and evidence refs)

## Output

```json
{"checks": {"evidence": {"pass": true, "note": "..."}, ...},
 "criteria_failed": [],
 "verdict": "proceed_to_human_gate | revise | block",
 "revision_instructions": []}
```
