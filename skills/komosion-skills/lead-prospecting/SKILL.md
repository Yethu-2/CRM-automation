---
name: lead-prospecting
description: Phase 3 skill that researches the market for potential leads and proposes them for human review, with evidence of why each may be relevant and what is unknown. Do not deploy until data sources and consent rules are agreed. Use when asked to find prospects, potential clients, target companies or new leads from market research, or to identify who to approach in a sector or region.
---

# Lead prospecting (Phase 3, deploy after Phases 1 and 2 are stable)

Prospecting differs from the rest of the workflow: it is outbound, volume-prone, and touches personal and contact data, so mistakes damage reputation and may breach privacy or anti-spam rules. Build it conservatively and keep a human in every step that creates records or sends anything.

## Preconditions (confirm before any run)

- Approved data sources are listed (see `references/prospecting-rules.md`).
- The target definition is stated by a human for this run (sector, region, size, need). Treat it as a hypothesis to explore, not a scoring model.
- The applicable privacy and outreach rules for the target region are known to the team.

If any precondition is missing, stop and ask for it.

## Steps

1. **Define the search** from the human's target. Restate it back in one line.
2. **Research** with approved sources. For each candidate company record: why it may be relevant (cited evidence), what is unknown, and the source and date.
3. **Dedupe against the CRM** with `entity-resolution`. Existing organisations are flagged, never re-added as new leads.
4. **Enrich lightly** using `company-context-brief` only for shortlisted candidates.
5. **Propose, do not create.** Present candidates as proposals for human review. Approved ones go to the CRM's leads inbox (not straight into deals) via `crm-action-gateway`.
6. **Do not rank by a numeric score.** Order by strength of evidence and state each candidate's evidence gaps (evidence-discipline).
7. Log what was searched, what was found and what was excluded, so the run is reproducible.

## Limits

Cap the number of candidates per run (default 20) so reviewers can actually review them. Never contact anyone from this skill. Business-published contact details only; never infer or guess email addresses.
