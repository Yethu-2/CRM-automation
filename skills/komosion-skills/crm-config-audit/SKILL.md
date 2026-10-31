---
name: crm-config-audit
description: Read-only audit of a CRM's configuration (pipelines, stages, custom fields, native automations, deal hygiene) that finds misconfiguration before an agent is layered on top. Use at client onboarding, when a CRM feels cluttered, confusing or untrusted, when automation seems excessive or missing, when stage or field data looks wrong, or when someone asks to review, clean up, health-check or sanity-check a Pipedrive, Twenty or other CRM setup, even if they do not say "audit".
---

# CRM configuration audit

Most CRM trouble comes from setup, not software: too many overlapping automations, too few, fields nobody fills, stages nobody can define, deals with no next step. An agent on top of a misconfigured CRM automates the confusion. Audit first. This skill only reads; it never changes configuration.

## Steps

1. **Read configuration** through the CRM connector (for Pipedrive, start with `getAccountContext` for pipelines, stages and custom fields; list deals and activities as needed). Export into the input shape in `scripts/audit_pipeline.py`'s docstring.
2. **Run the deterministic checks**: `python scripts/audit_pipeline.py crm_export.json --stale-days 30`. It reports stages without defined exit criteria, near-duplicate custom fields, rarely filled fields, open deals without a next activity, and stale open deals.
3. **Review automations with judgment.** The script lists enabled native automations; you assess:
   - Do two automations act on the same trigger or field? (overlap causes confusing behaviour)
   - Is any automation writing data the agent will also write? Decide a single owner for each field.
   - Is a basic step (assigning a follow-up task, stage-change logging) missing entirely?
4. **Check the purpose.** A CRM exists to track relationships and the next action. Flag where the setup tracks activity but not the relationship, or where stage values and probabilities are estimates nobody validates; recommend recording the evidence behind a stage rather than relying on the percentage.
5. **Report**: each finding with severity (high, medium, low), why it matters, and a recommended fix. Group by quick wins and structural changes. Do not apply fixes; changes go through the human and `crm-action-gateway`.

## Principle for the agent era

Keep native automation minimal and unambiguous: the agent should be the single, auditable decision layer, with native automations limited to simple deterministic housekeeping. Each field should have exactly one writer.
