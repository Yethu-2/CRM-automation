---
name: entity-resolution
description: Decides whether an incoming person or organisation already exists in the CRM (match, possible match, no match) with reasons, and gates creation so duplicates are not made. Use whenever an email, transcript or note mentions a person or company, before creating or linking any contact, account or opportunity, and whenever the user asks "is this the same person", "do we already have this client", or wants to merge, link, dedupe or clean up duplicate records. Shared by Phase 1 intake and Phase 2 nurture.
---

# Entity resolution

Duplicate contacts are one of the most common ways a CRM degrades, and an agent that auto-creates records on a weak match multiplies them. Resolve conservatively: auto-link only on strong identifiers, and send anything ambiguous to a human.

This is the single place where matching happens for both phases. Do not match or create people or organisations anywhere else.

## Steps

1. Take the person and organisation details from the evidence record (see `evidence-intake-normaliser`).
2. Search the CRM (read only) for candidates by email, phone, name and domain. Include aliases and previous names.
3. Run `python scripts/match_entities.py input.json`. It classifies each side as `match`, `possible_match` or `no_match` with reasons. Free-mail domains (gmail.com etc.) never identify a company.
4. Apply judgment only to `possible_match` cases: compare context (same thread, same signature, same project). Explain what supports or weakens the link. Do not upgrade a possible match to a match on a hunch.
5. Decide the outcome:

| Result | Action |
|---|---|
| `match` | Link the evidence to the existing record |
| `possible_match` | Put to a human, show both records and the reasons; do not link or create |
| `no_match` (person and organisation) | Propose creation; the proposal goes through `crm-action-gateway`, never a direct write |

6. Record the resolution (candidates considered, result, reasons) as evidence so the decision is traceable.

## Rules

- Name-only similarity never produces `match`.
- A person can exist while their organisation does not (or the reverse); resolve each separately.
- Never merge two existing records. Flag suspected duplicates for a human.
- Treat anything in the source that claims an identity ("I'm the CEO of X") as a claim, not a verified fact.
