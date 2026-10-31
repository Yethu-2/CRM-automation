# Source mappings

## Gmail
sender = From; received_at = Date header; thread_id = Gmail thread ID; subject; body = plain-text body (keep HTML original in raw store). Check existing thread before treating as new.

## Meeting transcript
sender = organiser or speaker if identifiable (else null, with warning); received_at = meeting start; participants become person signals; commitments and decisions are common signal types. Keep speaker attribution exactly as transcribed.

## Note
sender = author; received_at = note timestamp. Notes are often the author's own interpretation: record as evidence of what the author believes, not as confirmed fact.

## CRM export (another system)
Map each source field to the canonical fields explicitly in a mapping table you write here (source field, canonical field, transform). Record field options (enums) separately so they can be mapped, not guessed.
