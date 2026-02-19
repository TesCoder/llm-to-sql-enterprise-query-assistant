from __future__ import annotations

"""
How to test DeepSeek connection:

A small CLI has been added to nl2sql/llm.py. 
It auto-loads the repo-root .env and calls the model.

To check connectivity, run:
    python nl2sql/llm.py --ping

Expected output:
    pong

To make a real prompt request:
    python nl2sql/llm.py "Say hello"

"""
import os
import re
import sys
from typing import Optional

from openai import AsyncOpenAI
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

_FENCED_SQL_RE = re.compile(r"```(?:sql)?\s*([\s\S]*?)```", flags=re.IGNORECASE)


def _extract_sql(text: str) -> str:
    # Models occasionally wrap SQL in markdown fences or add a "SQL:" label. We aggressively
    # normalize because the API layer enforces strict "single statement" rules.
    if not text:
        return ""

    raw = text.strip()

    m = _FENCED_SQL_RE.search(raw)
    if m:
        raw = (m.group(1) or "").strip()

    raw = re.sub(r"^\s*sql\s*:\s*", "", raw, flags=re.IGNORECASE).strip()

    # Normalize a trailing semicolon away (the API rejects mid-query semicolons).
    if raw.endswith(";"):
        raw = raw[:-1].strip()

    return raw


def _load_dotenv_if_present() -> None:
    """
    Allow running this module directly without manually exporting env vars.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    try:
        from pathlib import Path

        base_dir = Path(__file__).resolve().parent.parent
        load_dotenv(dotenv_path=base_dir / ".env")
    except Exception:
        return


def _strip_wrapping_quotes(value: Optional[str]) -> Optional[str]:
    """
    Docker/Compose env files sometimes preserve quotes. Strip a single matching pair of
    wrapping quotes to avoid values like "'sk-...'" or '"https://.../v1"'.
    """
    if value is None:
        return None
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {"'", '"'}:
        return v[1:-1]
    return v


def _client() -> AsyncOpenAI:
    # DeepSeek exposes an OpenAI-SDK compatible API. We use the same `AsyncOpenAI` client
    # for both providers by swapping keys + base URLs.
    #
    # Env var caveat: different demos/providers use different names (OPENAI_BASE_URL vs
    # OPENAI_API_URL). We accept a few aliases so local `.env` files keep working.
    kwargs = {}

    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    openai_compat_base_url = (
        os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_URL") or ""
    ).strip()
    if not provider:
        if os.getenv("DEEPSEEK_API_KEY"):
            provider = "deepseek"
        elif "deepseek.com" in openai_compat_base_url:
            # Back-compat: some setups store the DeepSeek base_url under an OpenAI-ish env var.
            provider = "deepseek"
        else:
            provider = "openai"

    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        # DeepSeek is OpenAI-SDK compatible via base_url.
        base_url = (
            os.getenv("DEEPSEEK_BASE_URL")
            or os.getenv("DEEPSEEK_API_URL")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("OPENAI_API_URL")
            or "https://api.deepseek.com/v1"
        )
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_URL")

    api_key = _strip_wrapping_quotes(api_key)
    base_url = _strip_wrapping_quotes(base_url)

    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    kwargs["timeout"] = float(
        os.getenv("LLM_TIMEOUT_SECONDS")
        or os.getenv("DEEPSEEK_TIMEOUT_SECONDS")
        or os.getenv("OPENAI_TIMEOUT_SECONDS")
        or "30"
    )
    return AsyncOpenAI(**kwargs)


def _model() -> str:
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if not provider:
        openai_compat_base_url = (
            os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_URL") or ""
        ).strip()
        if os.getenv("DEEPSEEK_API_KEY") or "deepseek.com" in openai_compat_base_url:
            provider = "deepseek"
        else:
            provider = "openai"

    if provider == "deepseek":
        return os.getenv("DEEPSEEK_MODEL") or os.getenv("LLM_MODEL") or "deepseek-chat"
    return os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL") or "gpt-4o-mini"


def _system_prompt() -> str:
    # This is the "pre-prompt" sent with every NL→SQL request. It's intentionally strict:
    # - forces SQL-only output (simplifies parsing)
    # - forces read-only SQL (paired with server-side enforcement)
    #
    # Important: prompts are NOT a security boundary. The API re-validates generated SQL
    # with `ensure_select_only()` and adds a LIMIT if missing.
    return "\n".join(
        [
            "You convert natural-language questions into safe, read-only SQL for SQLite.",
            "",
            "Output rules (must follow):",
            "- Return ONLY the SQL text (no markdown, no code fences, no explanation).",
            "- Single statement. Do NOT include semicolons.",
            "- Read-only: SELECT (CTEs allowed only if they end in a SELECT).",
            "- Use ONLY the tables/columns provided in the schema.",
            "- Always include a LIMIT clause. Use LIMIT 200 unless the user requests a smaller limit.",
            "- If the user asks for an order count and you join orders to order_items, use COUNT(DISTINCT orders.order_id).",
            "- Prefer clear aliases like total_sales, orders_count, month.",
            "",
            "If the question cannot be answered from the schema, output exactly: NO_SQL",
        ]
    )


def _user_prompt(question: str, schema: str, role: str) -> str:
    # The schema is embedded directly in the prompt so the model can "see" exactly which
    # tables/columns exist. This is the primary grounding mechanism to reduce hallucinations.
    return "\n".join(
        [
            f"Role: {role}",
            "Schema:",
            schema.strip(),
            "",
            "Question:",
            question.strip(),
            "",
            "SQL:",
        ]
    )


def _repair_prompt(
    question: str, schema: str, role: str, previous_sql: str, error: str
) -> str:
    # When the first attempt fails at execution-time, we feed the DB error back to the model
    # along with the prior SQL. This often fixes small issues (typos, wrong table aliasing).
    return "\n".join(
        [
            f"Role: {role}",
            "Schema:",
            schema.strip(),
            "",
            "Question:",
            question.strip(),
            "",
            "The previous SQL was:",
            previous_sql.strip(),
            "",
            "It failed with this error:",
            error.strip(),
            "",
            "Return corrected SQL only.",
            "SQL:",
        ]
    )


async def generate_sql(
    *,
    question: str,
    schema: str,
    role: str,
    previous_sql: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    """
    Generate SQL from a natural-language question using an OpenAI-compatible API.

    Environment variables:
    - LLM_PROVIDER: "deepseek" (default if DEEPSEEK_API_KEY is set) or "openai"
    - DEEPSEEK_API_KEY: DeepSeek API key
    - DEEPSEEK_BASE_URL: defaults to https://api.deepseek.com/v1
    - DEEPSEEK_MODEL (or LLM_MODEL): defaults to deepseek-chat
    - OPENAI_API_KEY: OpenAI API key (if provider=openai)
    - OPENAI_BASE_URL: optional (for OpenAI-compatible endpoints)
    - OPENAI_MODEL (or LLM_MODEL): model name (default: gpt-4o-mini)
    """
    system = _system_prompt()
    if previous_sql and error:
        user = _repair_prompt(question, schema, role, previous_sql, error)
    else:
        user = _user_prompt(question, schema, role)

    client = _client()
    try:
        # We send the schema-containing user prompt + strict system prompt on every call.
        # `temperature=0` keeps SQL stable/deterministic for the same question+schema.
        resp = await client.chat.completions.create(
            model=_model(),
            temperature=0,
            max_tokens=int(
                os.getenv("LLM_MAX_TOKENS")
                or os.getenv("DEEPSEEK_MAX_TOKENS")
                or os.getenv("OPENAI_MAX_TOKENS")
                or "300"
            ),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except AuthenticationError as exc:
        raise RuntimeError(
            "LLM authentication failed. Check your provider key (e.g. `DEEPSEEK_API_KEY`) and base URL (e.g. `DEEPSEEK_BASE_URL`)."
        ) from exc
    except RateLimitError as exc:
        raise RuntimeError("LLM rate limit exceeded. Try again shortly.") from exc
    except (APITimeoutError, APIConnectionError) as exc:
        raise RuntimeError(
            "LLM request failed (timeout/connection). Try again."
        ) from exc
    except APIStatusError as exc:
        raise RuntimeError(f"LLM request failed (HTTP {exc.status_code}).") from exc
    except OpenAIError as exc:
        raise RuntimeError("LLM request failed.") from exc

    content = (resp.choices[0].message.content or "").strip()
    return _extract_sql(content)


async def chat_text(prompt: str) -> str:
    """
    Minimal chat call (useful for connection smoke tests).
    """
    client = _client()
    try:
        resp = await client.chat.completions.create(
            model=_model(),
            temperature=0,
            max_tokens=int(
                os.getenv("LLM_MAX_TOKENS")
                or os.getenv("DEEPSEEK_MAX_TOKENS")
                or os.getenv("OPENAI_MAX_TOKENS")
                or "200"
            ),
            messages=[{"role": "user", "content": prompt}],
        )
    except AuthenticationError as exc:
        raise RuntimeError(
            "LLM authentication failed. Check your provider key (e.g. `DEEPSEEK_API_KEY`) and base URL (e.g. `DEEPSEEK_BASE_URL`)."
        ) from exc
    except RateLimitError as exc:
        raise RuntimeError("LLM rate limit exceeded. Try again shortly.") from exc
    except (APITimeoutError, APIConnectionError) as exc:
        raise RuntimeError(
            "LLM request failed (timeout/connection). Try again."
        ) from exc
    except APIStatusError as exc:
        raise RuntimeError(f"LLM request failed (HTTP {exc.status_code}).") from exc
    except OpenAIError as exc:
        raise RuntimeError("LLM request failed.") from exc

    return (resp.choices[0].message.content or "").strip()


def _cli_usage() -> str:
    return "\n".join(
        [
            "Usage:",
            "  python nl2sql/llm.py --ping",
            '  python nl2sql/llm.py "Say hello"',
            "",
            "Notes:",
            "- Loads repo-root .env automatically (if python-dotenv is installed).",
            "- Uses DeepSeek by default when OPENAI_API_URL/OPENAI_BASE_URL points at deepseek.com.",
        ]
    )


async def _cli_main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(_cli_usage())
        return 0

    if argv[0] == "--ping":
        out = await chat_text("Reply with exactly: pong")
        print(out)
        return 0

    prompt = " ".join(argv).strip()
    if not prompt:
        print(_cli_usage())
        return 2

    out = await chat_text(prompt)
    print(out)
    return 0


if __name__ == "__main__":
    import asyncio

    _load_dotenv_if_present()
    raise SystemExit(asyncio.run(_cli_main(sys.argv[1:])))
