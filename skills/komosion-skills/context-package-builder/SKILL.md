---
name: context-package-builder
description: Builds the minimum relevant context package an agent needs before interpreting a new client signal, combining the current signal and evidence, CRM context, and only the historical signals that matter. Use whenever new evidence arrives (email, transcript, note, meeting) and a reasoning, assessment or recommendation step is about to run, or when asked to gather context, history or background on a client, deal or contact. Prefer this over dumping full client history.
---

# Context package builder

Reasoning quality depends on context quality. Too little history causes unsupported assumptions; too much wastes tokens and buries the signal. Retrieve the minimum relevant history, not all of it. Follow the `evidence-discipline` skill for everything you write.

## Package components

Every package contains all ten; leave a component empty rather than omitting it, so gaps are visible.

| Component | Purpose |
|---|---|
| `current_signal` | What changed (with ID) |
| `current_evidence` | Grounds the signal (IDs) |
| `crm_context` | Organisation, Person, Opportunity |
| `historical_signals` | Selected prior signals (IDs) |
| relationship per historical signal | Why that history is relevant |
| `known_facts` | Confirmed facts, to prevent assumptions |
| `previous_decisions_actions` | Commercial continuity |
| `outcomes` | What happened after earlier decisions |
| `information_gaps` | Unresolved questions |
| `evidence_references` | Every ID used, for traceability |

## Selecting history: relevance first, recency second

For each candidate historical signal, ask whether it matches **at least one** rule:

1. Same business issue
2. Same opportunity
3. Same stakeholder
4. Direct relationship (supports, contradicts or explains the current signal)
5. Previous decision impact
6. Previous outcome relevance

If none match, exclude it however recent it is. If one or more match, write a one-line `relationship_to_current`. A signal without that sentence is not included, because the reader cannot judge why it is there.

Recency only ranks otherwise similar candidates. A highly relevant older signal beats a recent unrelated one.

## Procedure

1. Read the current signal and evidence. Identify the entities and issue.
2. Pull CRM context (read only) and candidate history from the memory store.
3. Tag each candidate with the rules it matches. Write `rules` as booleans keyed by the six names above (`same_business_issue`, `same_opportunity`, `same_stakeholder`, `direct_relationship`, `previous_decision_impact`, `previous_outcome_relevance`), plus `occurred_at` and `relationship_to_current`.
4. Run `python scripts/rank_history.py candidates.json --max 5` to apply the selection and ranking deterministically. It returns `selected`, `overflow` and `excluded` with reasons.
5. Assemble the package. Add `known_facts` (each with evidence IDs) and `information_gaps` (see evidence-discipline format).
6. Keep the exclusion log with the package so a reviewer can see what was left out and why.

## Output

A JSON object with the ten components plus `excluded_log`. Every ID mentioned anywhere must also appear in `evidence_references`.
