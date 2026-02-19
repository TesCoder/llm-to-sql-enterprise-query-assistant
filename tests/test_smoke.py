from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from nl2sql.presets import load_preset_index, match_preset, normalize_question
from service.app import ensure_limit, ensure_select_only


def test_normalize_question_basic() -> None:
    assert (
        normalize_question("  What are the top 10 states by sales?   ")
        == "what are the top 10 states by sales"
    )


def test_match_preset_alias() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    index = load_preset_index(repo_root / "nl2sql" / "presets.json")
    preset = match_preset(index, "sales by region")
    assert preset is not None
    assert preset.id == "sales_by_region"


def test_ensure_select_only_allows_select() -> None:
    assert ensure_select_only("SELECT 1") == "SELECT 1"


def test_ensure_select_only_allows_cte() -> None:
    sql = "WITH x AS (SELECT 1 AS n) SELECT n FROM x"
    assert ensure_select_only(sql) == sql


def test_ensure_select_only_blocks_dml() -> None:
    with pytest.raises(HTTPException):
        ensure_select_only("DROP TABLE orders")


def test_ensure_select_only_blocks_multi_statement() -> None:
    with pytest.raises(HTTPException):
        ensure_select_only("SELECT 1; SELECT 2")


def test_ensure_limit_appends_default() -> None:
    sql, effective = ensure_limit("SELECT 1")
    assert sql.endswith("LIMIT 200")
    assert effective == 200


def test_ensure_limit_keeps_existing_limit() -> None:
    sql, effective = ensure_limit("SELECT 1 LIMIT 10")
    assert sql == "SELECT 1 LIMIT 10"
    assert effective == 10
