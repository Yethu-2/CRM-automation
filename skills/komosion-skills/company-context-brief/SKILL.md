---
name: company-context-brief
description: Builds a short, sourced brief on a company (what it does, size, leadership, recent news, relevance to Komosion) with a source and date on every claim and unverified items clearly labelled. Use when a new organisation appears and background would improve an assessment, when preparing for a call, or when asked to research, look up, profile or find information about a company or client, even if they only give a name or domain. Feeds contextual-assessment; does not update CRM fields on its own.
---

# Company context brief

Background should reduce uncertainty, not add unverified claims. Every statement is traceable to a source and date, and anything that cannot be confirmed is labelled as such. Apply `evidence-discipline`.

## Steps

1. **Identify the company precisely** using the domain and CRM record. Run `entity-resolution` if unsure which organisation is meant; same-name companies are common.
2. **Search**: the company's own site first, then reputable independent sources (news, registries, filings, professional profiles). Prefer primary sources over aggregators. Use focused queries; one search per question.
3. **Record each claim** with: statement, source URL, source date, and status (`confirmed` = from the company's own or an official source, `reported` = a credible third party, `unverified` = single weak source).
4. **Stay relevant.** Collect what matters to the assessment dimensions (nature of work, scale, likely needs, risk signals, relationship hooks). Skip trivia.
5. **Keep personal data minimal.** Include roles and business-published information about decision-makers only as needed; do not compile private details about individuals.
6. **List what could not be found** as information gaps.

## Where it goes

The brief is stored as evidence (with its sources and retrieval date) and offered to `contextual-assessment` as context. It never writes CRM fields by itself; any proposed field update (industry, size, website) goes through `crm-action-gateway` for approval. Information ages, so mark the retrieval date and treat briefs older than a few months as needing a refresh.

## Output

Use `references/brief-template.md`.
