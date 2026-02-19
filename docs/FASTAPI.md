# FastAPI backend documentation

This project’s backend is a **FastAPI** app served by **uvicorn**.

## What runs what
- **FastAPI**: the Python web framework where routes/endpoints are defined.
- **uvicorn**: the ASGI web server that hosts the FastAPI app on a port (default `8000`).

In this repo:
- App code: `service/app.py`
- FastAPI instance: `app = FastAPI(...)`

## Local setup (backend + database)

### 1) Create/activate the virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Load the SQLite database
This project uses a local SQLite file `enterprise.db` and loads it from `data/train.csv`.

```bash
python data/load_data.py
```

Schema docs:
- `data/SCHEMA.md`
- `data/DATASET.md`

### 3) Start the FastAPI server

```bash
uvicorn service.app:app --reload
```

- **Host/port**: `http://127.0.0.1:8000`
- `--reload` restarts the server when you change Python files.

## Run with Docker (optional)

Prereq: install Docker and make sure it’s running (e.g. Docker Desktop / Colima). If `docker` is not found, Docker isn’t installed yet.

```bash
docker compose up --build
```

Then open `http://127.0.0.1:8000/`.

Notes:
- The Docker image builds `enterprise.db` from `data/train.csv` at build time.
- To enable LLM fallback, set `OPENAI_API_KEY` / `OPENAI_API_URL` (DeepSeek) via your shell or a local `.env` file (see `.env.example`).

## Environment variables

The backend loads environment variables from `.env` (via `python-dotenv`) and/or your shell environment.

| name | example | purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./enterprise.db` | Connection string used by the backend to query the database |
| `PORT` | `8000` | Port to run the API on (when using `python service/app.py`) |
| `OPENAI_API_KEY` | `sk-...` | OpenAI key (or DeepSeek key when using `OPENAI_API_URL` pointing at DeepSeek); enables LLM fallback in `POST /ask` |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name to use for NL → SQL (defaults to `gpt-4o-mini`) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Optional base URL for OpenAI-compatible providers |
| `OPENAI_API_URL` | `https://api.deepseek.com/v1` | Alias for `OPENAI_BASE_URL` (some setups use this name) |
| `OPENAI_TIMEOUT_SECONDS` | `30` | Optional request timeout (seconds) for the LLM call |
| `OPENAI_MAX_TOKENS` | `300` | Optional max tokens for the generated SQL response |
| `LLM_PROVIDER` | `deepseek` | Provider selector (`deepseek` or `openai`). Defaults to `deepseek` when `DEEPSEEK_API_KEY` is set |
| `DEEPSEEK_API_KEY` | `sk-...` | DeepSeek API key (recommended for this project) |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | Base URL for DeepSeek (OpenAI-SDK compatible) |
| `DEEPSEEK_API_URL` | `https://api.deepseek.com/v1` | Alias for `DEEPSEEK_BASE_URL` (some setups use this name) |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek model name (defaults to `deepseek-chat`) |
| `LLM_TIMEOUT_SECONDS` | `30` | Generic timeout override (wins over provider-specific timeouts) |
| `LLM_MAX_TOKENS` | `300` | Generic max-tokens override (wins over provider-specific max tokens) |

Notes:
- DeepSeek is OpenAI-SDK compatible. If you set `OPENAI_API_URL=https://api.deepseek.com/v1`, you can put your DeepSeek key in `OPENAI_API_KEY`.
- LLM connectivity smoke test: `python nl2sql/llm.py --ping`

## Using the built-in “UI” (recommended)
FastAPI automatically serves interactive API docs:
- **Swagger UI**: `http://127.0.0.1:8000/docs`

This is the easiest way to debug requests and inspect full response payloads.

## User UI (natural language)
This repo includes a simple, centered UI (ChatGPT/Google-like) for entering **natural-language questions**:
- Open: `http://127.0.0.1:8000/ui/`

Today, it calls `POST /ask`.
- If the question matches a preset in `nl2sql/presets.json`, the backend runs that SQL (no LLM cost).
- Otherwise it calls the configured LLM (DeepSeek by default) to generate safe SQL, then executes it.

To confirm which path ran, look at the response fields:
- `source="verified"` → matched `nl2sql/presets.json` (no LLM call)
- `source="llm"` → LLM generated SQL
- `preset_id` is present only when `source="verified"`

In the `/ui` page, toggle **Dev** (footer) to reveal technical details like `source`, `preset_id`, executed SQL, and debug JSON.

## Simple web UI (SQL console)
This repo also includes a minimal web UI that lets you run SQL queries (SELECT-only) against `POST /query`:
- Open: `http://127.0.0.1:8000/manual/`

It’s intentionally lightweight (static HTML/CSS/JS) and requires no Node tooling.

## Endpoints

### `GET /health`
Returns a simple health status.

**Response**

```json
{ "status": "ok" }
```

### `POST /query`
Executes a SQL query against the database and returns JSON rows.

This is currently a **developer/debug endpoint**. It intentionally accepts raw SQL but enforces safety rules.

**Request body**

```json
{ "sql": "SELECT ..." }
```

**Behavior / guardrails**
- **SELECT-only**: rejects anything that does not start with `SELECT`.
- **No multi-statement**: rejects any query containing `;` in the middle.
- **Blocks common unsafe keywords**: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, etc.
- **Default LIMIT**: if your query has no `LIMIT`, the API appends `LIMIT 200`.

**Response body**

```json
{
  "sql": "SELECT ... LIMIT 200",
  "rows": [ { "col": "value" } ],
  "row_count": 1
}
```

### `POST /ask`
Accepts a **natural-language** question.

This endpoint first checks **presets** (`nl2sql/presets.json`) to avoid unnecessary LLM calls for common requests.
- **Preset match**: executes preset SQL and returns rows with `source="verified"`.
- **No match**: calls the LLM to generate SQL and returns rows with `source="llm"`.

**Request body**

```json
{
  "question": "Show total sales by region",
  "role": "analyst"
}
```

**Response body (preset match example)**

```json
{
  "question": "Show total sales by region",
  "role": "analyst",
  "source": "verified",
  "preset_id": "sales_by_region",
  "sql": "SELECT ... LIMIT 200",
  "rows": [ { "region": "West", "total_sales": 710219.6845 } ],
  "row_count": 4,
  "message": "Verified preset matched (no LLM call). Here are the results.",
  "meta": { "limit_applied": 200, "latency_ms": 123 },
  "status": "ok"
}
```

**Response body (LLM fallback example)**

```json
{
  "question": "Which region has the highest total sales?",
  "role": "analyst",
  "source": "llm",
  "preset_id": null,
  "sql": "SELECT ... LIMIT 200",
  "rows": [ { "region": "West", "total_sales": 710219.6845 } ],
  "row_count": 4,
  "message": "Here are the results.",
  "meta": { "limit_applied": 200, "latency_ms": 456 },
  "status": "ok"
}
```

## Examples

### Query from Swagger UI
1) Open `http://127.0.0.1:8000/docs`
2) Expand `POST /query`
3) Click **Try it out**
4) Paste JSON like:

```json
{ "sql": "SELECT COUNT(*) AS orders_count FROM orders" }
```

5) Click **Execute**

### Query with curl

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT COUNT(*) AS orders_count FROM orders"}'
```

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT region, SUM(oi.sales) AS total_sales FROM order_items oi JOIN orders o ON o.order_id = oi.order_id GROUP BY region ORDER BY total_sales DESC"}'
```

### Ask with curl

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Show total sales by region","role":"analyst"}'
```

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Which region has the highest total sales?","role":"analyst"}'
```

## Troubleshooting

### “Couldn’t connect to server”
This usually means `uvicorn` is not running yet.

Start the server in one terminal:

```bash
uvicorn service.app:app --reload
```

Then call it from another terminal (or use `http://127.0.0.1:8000/docs`).

### “Address already in use” (port 8000)
Another process is already using port 8000. Either stop that process or run on another port:

```bash
uvicorn service.app:app --reload --port 8001
```

### “Only SELECT statements are allowed”
The API blocks DDL/DML and multi-statement SQL. Send a single `SELECT` query.

### “SQL execution failed: no such table …”
The database likely hasn’t been loaded yet. Recreate/load it:

```bash
python data/load_data.py
```

