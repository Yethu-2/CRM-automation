---
name: contextual-assessment
description: Phase 1 assessment of a new client or opportunity across six dimensions (value of work, expertise fit, delivery capacity, relationship, risks, opportunity cost), recording observation, evidence and unknowns for each and ending with a suggested relationship posture. Replaces ICP scoring. Use whenever a new lead, enquiry or first contact arrives, whenever someone asks whether to take on a client or opportunity, whether a lead is worth pursuing, or asks for a fit, qualification or triage view, even when they say "score" or "qualify".
---

# Contextual assessment

Scores and tiers feel precise but punish missing information and hide reasoning. This assessment instead records what is known, what is not, and why, and a human decides. There is no numeric score, tier or threshold. Apply `evidence-discipline` throughout.

## Steps

1. **Retrieve context first**, using `context-package-builder`: CRM relationship and history, prior evidence, internal capacity context, and similar **reviewed examples** from `human-review-capture` (cases where a human corrected an earlier assessment, with their rationale).
2. **Assess each of the six dimensions.** For every dimension store three things:
   - **Observation**: what the evidence shows (fact or labelled inference)
   - **Evidence reference**: IDs of the supporting evidence
   - **Unknowns**: what cannot yet be said

   | Dimension | Question |
   |---|---|
   | Value of work | What is the likely scope and commercial value of the work? |
   | Expertise fit | Does this match what Komosion does well? |
   | Delivery capacity | Can we deliver without displacing committed work? |
   | Relationship | What is the history or likely nature of the relationship? |
   | Risks | What could go wrong (scope, payment, dependencies)? |
   | Opportunity cost | What would taking this mean we cannot do? |

3. **Missing is not negative.** An unknown goes in Unknowns and the evidence gaps. It never lowers the assessment. If a dimension has no evidence at all, say "no evidence yet" and suggest how to get it.
4. **Draft the assessment**: pros, concerns/risks, opportunity or strategic upside, evidence gaps, suggested relationship posture, and next information or actions.
5. **Suggest a posture**: Active, Nurture, Hold or Decline, with the rationale. This is a suggestion; a human approves it.
6. Pass to `recommendation-evaluator`, then human review (approve, edit, defer, reject). Capture the outcome with `human-review-capture`.

## Capacity context

Delivery capacity needs a real source (a capacity sheet, calendar or project tool). If none is connected, write "no capacity source available" as an evidence gap and do not estimate it.

## Handoff

Active or Nurture continues into Phase 2 as a linked client/opportunity, the assessment context and evidence-graph references. It is not a "qualified" label. Hold or Decline is retained with its evidence so it can re-enter on a meaningful new signal.

See `references/assessment-schema.md` for the output shape.
