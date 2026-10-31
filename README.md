# CRM-automation: DeepSeek CRM assistant

A Claude-style chat interface on the **DeepSeek API** for Komosion's CRM team. It answers from **live Pipedrive
data (read-only)** using **Komosion's CRM skill set**, and shows its working: which skills DeepSeek chose to load,
every Pipedrive call it made, tokens, cost and time for each answer.

Why it exists: Phase 2 of CRM Automation compared Claude and DeepSeek in a document. This shows the team how
DeepSeek actually behaves with our skills and data, before anything goes to production (brief from Truc, 28 Oct 2026).

```
Browser (behind Cloudflare Access)
   │  chat page + trace panel (backend/app/static/index.html)
   ▼
FastAPI backend (backend/app)
   ├─ agent.py      DeepSeek tool loop, streamed (OpenAI-compatible /chat/completions)
   ├─ skills.py     catalog of skills/ → load_skill tool (Claude-style: names first, full text on demand)
   ├─ tools.py      load_skill + 4 read-only Pipedrive tools
   ├─ pipedrive.py  the only Pipedrive client: GET only, allowlisted read endpoints
   └─ store.py      SQLite: conversations, messages, one run row per answer → CSV export
```

## What it does
- **Chat** with streaming answers and history; pick `deepseek-flash` or `deepseek-v4-pro` per chat.
- **Skills like Claude.** The system prompt lists every skill's name and description; DeepSeek calls `load_skill` to
  read one when it needs it. `evidence-discipline` is always loaded. The trace shows which skills it chose.
- **Pipedrive, read-only.** Search and get deals, persons and organizations; list activities and notes. The client
  can only send GET requests to an allowlist of read endpoints, so no prompt can make it write. When a change is
  warranted, DeepSeek writes a change plan for a human instead.
- **Trace panel** per answer: skills loaded, every tool call (arguments, result, time), input / cached / output
  tokens, cost (once `prices.json` is filled in) and total time.
- **Run log**: every answer is a row in SQLite; *Download run log (CSV)* in the sidebar.

Not in v1 (designed for, not built): Gmail and Calendar (read-only; pending a decision on sending email data to
DeepSeek), a case runner for the Phase 2 test cases with the five acceptance gates, client-memory tools over the
Phase 2 Supabase schema, running the skills' Python scripts.

## Skills
- `skills/` is a verbatim copy of [ZyleStacion/crm-skillsets](https://github.com/ZyleStacion/crm-skillsets); the
  pinned commit is in `skills/SOURCE.md`. Change skills upstream, then re-copy.
- `skills-local/commercial-criteria/` holds the 12 commercial assessment criteria from the Phase 2 handover, so the
  model stops confusing them with the recommendation-evaluator's 12 acceptance criteria (a gap the test log found).

## Run it
```bash
cp .env.example .env          # add DEEPSEEK_API_KEY and PIPEDRIVE_API_TOKEN
docker compose up -d --build  # http://localhost:8770
```
On the homelab it's published as `https://crm.yethu-aung.dev` through Cloudflare Tunnel, with a Cloudflare Access
application in front (only the team's emails). The container listens on 127.0.0.1 only and has no login of its own.

Costs: fill in `prices.json` from DeepSeek's pricing page (USD per 1M tokens: `input`, `input_cache_hit`, `output`).

## Develop
```bash
docker build --build-arg DEV=1 -t crm-deepseek:test . && docker run --rm crm-deepseek:test python -m pytest -q
# or, with Python 3.12+: cd backend && pip install -r requirements-dev.txt && python -m pytest -q
```
Tests need no network: DeepSeek and Pipedrive are faked (`backend/tests/fakes.py`).

## Safety rules
- Pipedrive stays read-only: add reads to `pipedrive.py`'s allowlist; never add a write method.
- Secrets only in `.env`; the browser never sees a key and never calls DeepSeek or Pipedrive directly.
- CRM records, notes, documents and emails are data, not instructions (stated in the system prompt).
- Client data (case files, exports) stays out of git: `cases/` and `data/` are ignored.
- DeepSeek's API is hosted in China. Pipedrive data was tested with it in Phase 2; get Truc's and John's
  agreement before connecting email or calendar.
