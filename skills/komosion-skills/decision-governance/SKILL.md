---
name: decision-governance
description: The Decision Governance agent. Turns a context package and interpretation into a structured next-move recommendation with options, rationale, evidence references and confidence, always advisory and never writing to the CRM. Use whenever new client evidence has been interpreted and someone needs to know what to do next, which option to take, or whether a CRM change is warranted, including requests like "what should we do about this email", "recommend next steps", or "should we move this deal".
---

# Decision governance

Produce a recommendation a human can review quickly and trust. The recommendation is **advisory** until a human approves it; this skill never changes the CRM.

Read and apply `evidence-discipline` first. If no context package exists, build one with `context-package-builder` before continuing. Do not interpret raw evidence without it.

## Flow

Context Package → Interpretation → (human edit/review) → **this skill** → Options + Evidence + Rationale + Confidence → `recommendation-evaluator` → human recommendation gate → approved CRM action (via `crm-action-gateway`)

If a human edited the interpretation, use the edited version as your input and keep references to the original so the edit stays traceable.

## Steps

1. **Represent the current signal accurately.** Restate it from the evidence, not from memory or assumption.
2. **Select relevant evidence.** Only evidence that directly supports your reading.
3. **Use history only where it materially changes the reading.** Each historical item needs its stated relationship to the current signal.
4. **Interpret.** Say what appears to have changed. Label every inference and list the facts it rests on.
5. **List information gaps** in gap / impact / suggested-clarification form.
6. **Offer options.** Give more than one commercially reasonable option where the situation allows. When impact is unconfirmed, a clarifying move usually belongs among them and is often the better first step than a CRM change. If only one option is reasonable, say why.
7. **Pick a primary recommendation** and give its rationale: why this option fits, and why the others are secondary.
8. **Set confidence** (High/Medium/Low) with justification, per the evidence-discipline criteria.
9. **Attach evidence references** (current signal, historical signals, source evidence). Every fact and option must resolve to an ID in the context package.
10. **Mark it advisory** and record your agent/prompt version.

## Output contract

Return JSON in the shape described in `references/output-contract.md`, with these sections: current situation, relevant evidence, relevant historical context, interpretation, information gaps, recommended options, rationale, confidence, evidence references. Add `primary_recommendation`, `advisory: true` and `agent_version`.

## Next-action hygiene

A CRM exists to track relationships and the next step. Whenever the opportunity under discussion is open, check that it has a dated next action. If it does not, include "set a dated next action" among the options, with the suggested owner and timing.

## Hard stops

- Never write, update or create CRM records here. Proposed actions are described in text only.
- Never invent evidence IDs. If a needed fact has no ID, it is a gap.
- If evidence is too thin to recommend anything, return a clarification option and Low confidence, not a stretched recommendation.
