# Canonical evidence record

```json
{
  "evidence_id": "EV-<stable hash of source + source_id>",
  "source": "gmail | transcript | note | meeting | crm_export | other",
  "source_id": "id in the originating system",
  "thread_id": "conversation/thread identifier or null",
  "received_at_utc": "2026-10-04T08:30:00+00:00",
  "sender": {"name": "", "email": "normalised or null", "phone": "+E.164 or null"},
  "org_domain": "company domain or null (null for free-mail)",
  "is_free_mail": false,
  "subject": "",
  "language": "original language code",
  "raw_ref": "pointer to untouched original",
  "raw_sha256": "hash of original body",
  "warnings": []
}
```

Candidate signal:

```json
{"signal_id": "SIG-<n>", "evidence_id": "EV-...", "type": "person|account|concern|opportunity|commitment|decision",
 "statement": "what the source says", "passage": "exact supporting text or location"}
```

Rules: values that cannot be determined are `null` with a warning, never a guess. IDs are stable so re-ingesting the same message produces the same `evidence_id` (idempotent).
