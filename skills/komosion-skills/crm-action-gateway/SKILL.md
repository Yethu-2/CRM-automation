---
name: crm-action-gateway
description: Controlled gateway between AI recommendations and the CRM (Twenty, Pipedrive or other, via MCP or API). Enforces read, propose, execute tiers so nothing is written without matching human approval. Use whenever an agent needs to read CRM organisations, people or opportunities, propose a task, next action or record update, or execute an approved CRM change, or whenever the user says "update the CRM", "move the deal", "log this", "create a task", or "add the contact".
---

# CRM action gateway

MCP (or the API) is a controlled access mechanism here, not autonomous CRM authority. Humans stay in charge, and a CRM full of unreviewed AI edits is exactly the misconfiguration that makes teams stop trusting the system.

## Three tiers

| Tier | Allowed | Needs approval? |
|---|---|---|
| **Read** | Organisation, Person, Opportunity, relevant CRM context | No |
| **Propose** | Next action, task, potential record update, written as a proposal record (never a CRM write) | No |
| **Execute** | Apply an approved proposal to the CRM | **Yes**, always |

Discover available tools from the connected MCP server rather than assuming names; see `references/adapters.md`.

## Propose

Write each proposal as a record containing: `proposal_id`, target object and ID, exact payload (the fields and values to write), the recommendation and evidence references it came from, and the evaluator verdict. Nothing reaches the CRM at this stage.

For new people or organisations, include the matching result (match / possible match / no match, with reasons). Never propose auto-creation on a weak match; flag it for the reviewer.

## Execute

Run the checks below before any write. Any failure means no write.

1. A human approval record exists for this `proposal_id` with decision `approve` or `edit` and a reviewer.
2. The payload about to be written is identical to the approved payload (hash match). If the reviewer edited it, the edited payload is what was approved.
3. The evaluator verdict was not `block`.
4. The payload touches only the fields and object the approval covered.
5. The action has not already been executed (idempotency key).

Run `python scripts/verify_execution.py --approval approval.json --payload payload.json --evaluation evaluation.json`. If it exits non-zero, stop and report which check failed.

## After execution

1. Write to the evidence store first (action, approval, payload), then the CRM, then log the result. If the CRM write fails, the evidence record shows it was attempted.
2. Add the rationale to the CRM record (a note) so the CRM answers "what is the current state" and the evidence store answers "why".
3. Record the outcome as new evidence for the next cycle.
