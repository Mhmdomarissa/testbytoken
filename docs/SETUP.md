# Setup & run

## Prerequisites
- Python 3.11+
- An Anthropic API key (for the `/plan` endpoint)

## Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# install the real browser Playwright drives
playwright install chromium

# the LLM planner needs this
export ANTHROPIC_API_KEY=sk-ant-...

# run the API
uvicorn app:app --reload --port 8000
```

Check it's alive:
```bash
curl http://localhost:8000/health        # -> {"ok": true}
```

Run a real test from the command line (no frontend needed):
```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","checks":["page_load","title","https","performance"]}'
```

Or run the engine directly, bypassing the API:
```bash
python runner.py https://example.com
```

## Frontend

The demo frontend is a single file. Easiest path: serve it statically.

```bash
cd frontend
python3 -m http.server 5500
# open http://localhost:5500
```

By default the page calls the backend at `http://localhost:8000`. To change it,
set `window.API_BASE` before the script runs (or just edit the `API` const).

> Browsers block cross-origin requests unless CORS allows it. The backend already
> sets permissive CORS for the demo. Lock this down before any real deployment.

## Known TODO when you start (also listed in README)
- Screenshots aren't shown yet — the runner writes them to `backend/shots/` but the
  frontend can't reach them. Add a `/shots` static mount in `app.py` OR return the
  screenshot as base64 in the run result. This is build task #2.

## Deploy note (for the demo)
A single container is enough: install deps + `playwright install --with-deps chromium`,
run uvicorn, and serve `frontend/index.html` (either from the same FastAPI app via a
static mount, or any static host pointed at the API). Fly.io / Cloud Run / Render all
work. Warm-start matters later (so "Run" responds in ~2s) but isn't needed for the demo.
