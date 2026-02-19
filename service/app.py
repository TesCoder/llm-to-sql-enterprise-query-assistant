import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from databases import Database
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from nl2sql.llm import generate_sql
from nl2sql.presets import Preset, load_preset_index, match_preset
from nl2sql.schema import build_schema_context


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./enterprise.db")
database = Database(DATABASE_URL)

app = FastAPI(title="LLM-to-SQL Enterprise Query Assistant")

UI_DIR = BASE_DIR / "ui"
if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

MANUAL_DIR = BASE_DIR / "manual"
if MANUAL_DIR.exists():
    app.mount("/manual", StaticFiles(directory=str(MANUAL_DIR), html=True), name="manual")

PRESETS_JSON_PATH = BASE_DIR / "nl2sql" / "presets.json"
PRESET_INDEX = load_preset_index(PRESETS_JSON_PATH)


class QueryRequest(BaseModel):
    sql: str = Field(..., description="SELECT statement to run against the database")


class QueryResponse(BaseModel):
    sql: str
    rows: List[Dict[str, Any]]
    row_count: int


class AskRequest(BaseModel):
    question: str = Field(..., description="Natural-language question")
    role: str = Field("analyst", description="Role name (future: used for permissions)")


class AskResponse(BaseModel):
    question: str
    role: str
    source: str = Field(..., description="Where the answer came from (verified|llm|cache)")
    preset_id: Optional[str] = Field(
        default=None, description="Verified question id when source=verified"
    )
    sql: Optional[str] = None
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    message: str
    meta: Dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"


def ensure_select_only(sql: str) -> str:
    """Only allow SELECT statements; block other keywords and multi-statements."""
    normalized = sql.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1].strip()

    lowered = normalized.lower()
    forbidden = (
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "comment",
        "attach",
        "pragma",
        "vacuum",
    )

    # We accept CTEs (`WITH ... SELECT ...`) because many generated queries use them, but
    # we still enforce read-only semantics via keyword bans + single-statement checks.
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise HTTPException(status_code=400, detail="Only SELECT statements are allowed.")

    # Block multi-statement execution (e.g. "SELECT ...; DROP TABLE ...") even if the first
    # statement looks safe.
    if ";" in normalized:
        raise HTTPException(status_code=400, detail="Multiple statements are not allowed.")

    if any(re.search(rf"\\b{kw}\\b", lowered) for kw in forbidden):
        raise HTTPException(status_code=400, detail="Only SELECT statements are allowed.")

    return normalized


def ensure_limit(sql: str, default_limit: int = 200) -> tuple[str, int]:
    """Ensure a LIMIT exists. Returns (sql_with_limit, effective_limit)."""
    # This is a pragmatic safety cap (UI + API). It prevents accidental "runaway" queries.
    # We return the effective limit so callers can surface it in `meta` and debug behavior.
    m = re.search(r"\blimit\b\s+(\d+)\b", sql, flags=re.IGNORECASE)
    if m:
        try:
            return sql, int(m.group(1))
        except ValueError:
            return sql, default_limit
    return f"{sql} LIMIT {default_limit}", default_limit


@app.on_event("startup")
async def startup() -> None:
    await database.connect()


@app.on_event("shutdown")
async def shutdown() -> None:
    await database.disconnect()


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    if UI_DIR.exists():
        return RedirectResponse(url="/ui/")
    if MANUAL_DIR.exists():
        return RedirectResponse(url="/manual/")
    return RedirectResponse(url="/docs")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    # Avoid noisy 404s in the browser console.
    return Response(status_code=204)


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    sanitized_sql = ensure_select_only(req.sql)
    sql_with_limit, _limit = ensure_limit(sanitized_sql)

    try:
        rows = await database.fetch_all(text(sql_with_limit))
    except Exception as exc:  # pragma: no cover - defensive logging path
        raise HTTPException(status_code=400, detail=f"SQL execution failed: {exc}")

    row_dicts = [dict(row) for row in rows]
    return QueryResponse(sql=sql_with_limit, rows=row_dicts, row_count=len(row_dicts))


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    t0 = time.perf_counter()
    # Presets-first (aka "verified questions"): deterministic, reviewed SQL for common asks.
    # This keeps results reliable and avoids LLM latency/cost for repeated business questions.
    preset: Optional[Preset] = match_preset(PRESET_INDEX, req.question)
    if preset is not None:
        sanitized_sql = ensure_select_only(preset.sql)
        sql_with_limit, limit_applied = ensure_limit(sanitized_sql)

        try:
            rows = await database.fetch_all(text(sql_with_limit))
        except Exception as exc:  # pragma: no cover - defensive logging path
            raise HTTPException(status_code=400, detail=f"SQL execution failed: {exc}")

        row_dicts = [dict(row) for row in rows]
        return AskResponse(
            question=req.question,
            role=req.role,
            source="verified",
            preset_id=preset.id,
            sql=sql_with_limit,
            rows=row_dicts,
            row_count=len(row_dicts),
            # User-visible clarity: this path means a preset/verified question was used (no LLM call).
            message="Verified preset matched (no LLM call). Here are the results.",
            meta={
                "limit_applied": limit_applied,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            },
        )

    # LLM fallback: only used when there's no verified/preset match.
    # We always ground the model with a compact schema snapshot from the live DB so it uses
    # real tables/columns (reduces hallucinations) and so SQL validation can be strict.
    schema_context = await build_schema_context(database)
    try:
        candidate_sql = await generate_sql(
            question=req.question,
            schema=schema_context,
            role=req.role,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM generation failed: {exc}")

    if not candidate_sql or candidate_sql.strip().upper() == "NO_SQL":
        raise HTTPException(
            status_code=400,
            detail="Could not generate SQL for that question with the available schema.",
        )

    sanitized_sql = ensure_select_only(candidate_sql)
    sql_with_limit, limit_applied = ensure_limit(sanitized_sql)

    try:
        rows = await database.fetch_all(text(sql_with_limit))
    except Exception as exc:
        # One-shot correction loop: DB errors (unknown column, syntax) are common for generated SQL.
        # We retry exactly once to avoid infinite loops and to keep costs bounded.
        try:
            repaired_sql = await generate_sql(
                question=req.question,
                schema=schema_context,
                role=req.role,
                previous_sql=candidate_sql,
                error=str(exc),
            )
            if not repaired_sql or repaired_sql.strip().upper() == "NO_SQL":
                raise RuntimeError("Model could not repair SQL.")

            sanitized_sql = ensure_select_only(repaired_sql)
            sql_with_limit, limit_applied = ensure_limit(sanitized_sql)
            rows = await database.fetch_all(text(sql_with_limit))
            candidate_sql = repaired_sql
        except Exception:
            raise HTTPException(status_code=400, detail=f"SQL execution failed: {exc}")

    row_dicts = [dict(row) for row in rows]
    return AskResponse(
        question=req.question,
        role=req.role,
        source="llm",
        sql=sql_with_limit,
        rows=row_dicts,
        row_count=len(row_dicts),
        message="Here are the results.",
        meta={
            "limit_applied": limit_applied,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
