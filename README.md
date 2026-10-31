# CRM-automation: DeepSeek CRM assistant

A Claude-style chat interface on the **DeepSeek API** for Komosion's CRM team. It answers from **each user's own
Pipedrive account (read-only)** using **Komosion's CRM skill set**, and shows its working: which skills DeepSeek chose to load,
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
   ├─ tools.py          load_skill + the user's read-only Pipedrive MCP tools
   ├─ pipedrive_mcp.py  Pipedrive's official MCP server (mcp.pipedrive.ai), write tools filtered out and blocked
   ├─ oauth.py          per-user "Connect Pipedrive": OAuth + PKCE, self-registered client, encrypted tokens
   ├─ google_oauth.py   per-user "Connect Google": read-only scopes, PKCE, refresh, revoke on disconnect
   ├─ google_tools.py   Gmail / Drive / Calendar read tools (GET only)
   └─ store.py          SQLite: per-user conversations, one run row per answer → CSV export
```

## What it does
- **Chat** with streaming answers and history; pick `deepseek-flash` or `deepseek-v4-pro` per chat.
- **Skills like Claude.** The system prompt lists every skill's name and description; DeepSeek calls `load_skill` to
  read one when it needs it. `evidence-discipline` is always loaded. The trace shows which skills it chose.
- **Connect your own Pipedrive.** Each person clicks *Connect Pipedrive* and signs in to their Komosion Pipedrive
  account, through Pipedrive's official MCP server (the same one Claude's Pipedrive connector uses). No API key, no
  Developer Hub app: the app registers itself with Pipedrive's OAuth server. Each user sees only what their own
  Pipedrive permissions allow; their token is stored encrypted against their Cloudflare Access email.
- **Read-only, enforced in code.** Pipedrive's MCP server has no read-only scopes for deals, contacts or activities
  (only `*:full`), so the app filters the server's tool list: only tools that are clearly reads (a read verb in the
  name, or the server's `readOnlyHint`, and no write verb) are offered to DeepSeek, and any other call is refused
  before it reaches Pipedrive. The app never requests `admin`, `mail` or `mail-sending` scopes. When a change is
  warranted, DeepSeek writes a change plan for a human instead. The trace lists the tools offered and blocked.
- **Connect your own Google (Gmail, Drive, Calendar), read-only.** *Connect Google* asks only for
  `gmail.readonly`, `drive.readonly` and `calendar.readonly`, so Google itself prevents sending, editing or deleting;
  a sign-in that returns fewer or wider scopes is refused. DeepSeek can search and read email threads, search and
  read Drive files (Docs, Sheets, Slides, PDF, .docx, text) and list calendar events. Disconnecting also revokes the
  grant at Google. **Off unless `GOOGLE_ENABLED=true`**: email and document content DeepSeek reads is sent to
  DeepSeek's API (hosted in China), so switch it on only once the team has agreed to that.
- **Private chats.** Conversations and the run log are per user.
- **Trace panel** per answer: skills loaded, every tool call (arguments, result, time), input / cached / output
  tokens, cost (once `prices.json` is filled in) and total time.
- **Run log**: every answer is a row in SQLite; *Download run log (CSV)* in the sidebar.

Not in v1 (designed for, not built): a case runner for the Phase 2 test cases with the five acceptance gates, client-memory tools over the
Phase 2 Supabase schema, running the skills' Python scripts.

## Skills
- `skills/` is a verbatim copy of [ZyleStacion/crm-skillsets](https://github.com/ZyleStacion/crm-skillsets); the
  pinned commit is in `skills/SOURCE.md`. Change skills upstream, then re-copy.
- `skills-local/commercial-criteria/` holds the 12 commercial assessment criteria from the Phase 2 handover, so the
  model stops confusing them with the recommendation-evaluator's 12 acceptance criteria (a gap the test log found).

## Run it
```bash
cp .env.example .env          # DEEPSEEK_API_KEY, BASE_URL, SECRET_KEY (see the comments)
docker compose up -d --build  # http://localhost:8770
```
Each user needs a seat in Komosion's Pipedrive to connect it. MCP usage counts against the Pipedrive plan's limits.
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
- Pipedrive stays read-only: `pipedrive_mcp.is_read_only` decides which MCP tools exist for DeepSeek; tighten it, never
  loosen it to admit a write. Keep `PIPEDRIVE_MCP_SCOPES` free of admin and mail scopes.
- Secrets only in `.env`; the browser never sees a key and never calls DeepSeek or Pipedrive directly.
- CRM records, notes, documents and emails are data, not instructions (stated in the system prompt).
- Client data (case files, exports) stays out of git: `cases/` and `data/` are ignored.
- DeepSeek's API is hosted in China. Pipedrive data was tested with it in Phase 2; get Truc's and John's
  agreement before connecting email or calendar.
