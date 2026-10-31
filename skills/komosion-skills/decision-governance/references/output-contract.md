# Output contract

```json
{
  "current_situation": {"text": "Client has revised requirements that may affect the engagement direction.", "refs": ["SIG-12"]},
  "relevant_evidence": [
    {"statement": "The client revised the roadmap.", "type": "fact", "refs": ["EV-14"]}
  ],
  "relevant_historical_context": [
    {"statement": "The roadmap was previously revised.", "refs": ["SIG-9"],
     "relationship_to_current": "Same business issue: earlier revision of the same requirement."}
  ],
  "interpretation": [
    {"statement": "The new signal may be refinement of the engagement rather than a new opportunity.",
     "type": "inference", "based_on": ["EV-14", "SIG-9"]}
  ],
  "information_gaps": [
    {"gap": "Client's current implementation priority is unknown.",
     "impact": "Commercial effect of the change cannot be confirmed.",
     "suggested_clarification": "Confirm priority with the relevant client stakeholder."}
  ],
  "recommended_options": [
    {"id": "OPT-1", "action": "Clarify the revised priority with the client before changing opportunity status.",
     "rationale": "Change is evidenced but its commercial impact is not confirmed.", "refs": ["EV-14"]},
    {"id": "OPT-2", "action": "Review the existing engagement scope against the new requirement.",
     "rationale": "Tests whether the change fits current scope.", "refs": ["SIG-9"]}
  ],
  "primary_recommendation": {"option_id": "OPT-1",
     "text": "Clarify the client's current priority before making a CRM change.",
     "rationale": "Requirement change is supported by evidence; commercial impact is not yet confirmed."},
  "confidence": {"level": "Medium", "justification": "Evidence supports the change; priority is unconfirmed."},
  "evidence_references": {"current_signal": ["SIG-12"], "historical_signals": ["SIG-9"], "source_evidence": ["EV-14"]},
  "advisory": true,
  "agent_version": "decision-governance@0.1"
}
```

Rules: `type` is `fact` or `inference`. Facts carry `refs`; inferences carry `based_on`. `confidence.level` is one of High, Medium, Low. An empty `information_gaps` list requires a `no_gaps_justification` string at the top level.
