from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from databases import Database
from sqlalchemy import text

# We cache schema text by DB URL to avoid re-introspecting on every /ask call.
# This project’s schema is stable (loaded once from CSV), so a simple in-memory cache is fine.
_SCHEMA_CACHE: Dict[str, str] = {}


def _fallback_schema() -> str:
    return "\n".join(
        [
            "Database: SQLite",
            "Tables:",
            "- orders(order_id, order_date, ship_date, ship_mode, customer_id, customer_name, segment, country, city, state, postal_code, region)",
            "- order_items(row_id, order_id, product_id, category, sub_category, product_name, sales)",
            "Relationships:",
            "- order_items.order_id = orders.order_id",
            "Notes:",
            "- orders.order_date and orders.ship_date are ISO date strings (YYYY-MM-DD).",
        ]
    )


def _sql_quote(value: str) -> str:
    # Quote values as they should appear in SQL string literals.
    return "'" + value.replace("'", "''") + "'"


async def _distinct_values(
    database: Database,
    *,
    table: str,
    column: str,
    limit: int = 31,
) -> List[str]:
    """
    Fetch distinct non-empty values for a column (limited).

    These "value hints" are used to ground the LLM so it chooses correct columns/filters
    (e.g. Phones is a sub-category, not a category).
    """
    rows = await database.fetch_all(text(f"""
            SELECT DISTINCT {column} AS v
            FROM {table}
            WHERE {column} IS NOT NULL
              AND TRIM({column}) != ''
            ORDER BY {column}
            LIMIT {limit}
            """))
    out: List[str] = []
    for r in rows:
        v = r["v"]
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return out


async def _build_value_hints(database: Database, tables: List[str]) -> List[str]:
    """
    Add small-cardinality value lists for common categorical fields.

    This dramatically reduces LLM mistakes like filtering `category='Phones'` (zero rows)
    instead of using `sub_category='Phones'`.
    """
    targets: list[tuple[str, str]] = []
    if "order_items" in tables:
        targets.extend(
            [
                ("order_items", "category"),
                ("order_items", "sub_category"),
            ]
        )
    if "orders" in tables:
        targets.extend(
            [
                ("orders", "region"),
                ("orders", "segment"),
                ("orders", "ship_mode"),
            ]
        )

    hints: List[str] = []
    for table, column in targets:
        try:
            values = await _distinct_values(
                database, table=table, column=column, limit=31
            )
        except Exception:
            continue

        if not values:
            continue

        more = ""
        if len(values) > 30:
            values = values[:30]
            more = " (and more)"

        pretty = ", ".join(_sql_quote(v) for v in values)
        hints.append(f"- {table}.{column}: {pretty}{more}")

    return hints


async def _introspect_sqlite(
    database: Database,
) -> Tuple[List[str], Dict[str, List[str]], List[str]]:
    table_rows = await database.fetch_all(text("""
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%%'
            ORDER BY name
            """))
    # NOTE: the literal percent is escaped as `%%` because the `databases` SQLite backend uses
    # percent-formatting internally when compiling SQLAlchemy text queries.
    tables = [str(r["name"]) for r in table_rows]

    columns_by_table: Dict[str, List[str]] = {}
    relationships: List[str] = []

    for t in tables:
        col_rows = await database.fetch_all(text(f"PRAGMA table_info('{t}')"))
        cols: List[str] = []
        for r in col_rows:
            name = r["name"]
            col_type = r["type"]
            pk = r["pk"]
            label = f"{name} {col_type}".strip()
            if pk:
                label += " PK"
            cols.append(label)
        columns_by_table[t] = cols

        fk_rows = await database.fetch_all(text(f"PRAGMA foreign_key_list('{t}')"))
        for r in fk_rows:
            # columns: id, seq, table, from, to, on_update, on_delete, match
            other_table = r["table"]
            from_col = r["from"]
            to_col = r["to"]
            relationships.append(f"- {t}.{from_col} = {other_table}.{to_col}")

    return tables, columns_by_table, relationships


def _format_schema(
    tables: List[str],
    columns_by_table: Dict[str, List[str]],
    relationships: List[str],
    value_hints: Optional[List[str]] = None,
) -> str:
    lines: List[str] = ["Database: SQLite", "Tables:"]
    for t in tables:
        cols = columns_by_table.get(t) or []
        if cols:
            lines.append(f"- {t}({', '.join(cols)})")
        else:
            lines.append(f"- {t}")

    if relationships:
        lines.append("Relationships:")
        lines.extend(relationships)

    if value_hints:
        lines.append("Value hints:")
        lines.extend(value_hints)

    # Project-specific hints (helps the model with date grouping).
    if "orders" in tables:
        lines.append("Notes:")
        lines.append(
            "- orders.order_date and orders.ship_date are ISO date strings (YYYY-MM-DD)."
        )
        lines.append(
            "- For month buckets, you can use substr(order_date, 1, 7) AS month."
        )
        if "order_items" in tables:
            lines.append(
                "- orders has one row per order_id; order_items has line items. When counting orders after joining, use COUNT(DISTINCT orders.order_id)."
            )
    if "order_items" in tables:
        if "Notes:" not in lines:
            lines.append("Notes:")
        lines.append(
            "- order_items.category is broad; order_items.sub_category is the specific product type (e.g. 'Phones')."
        )

    return "\n".join(lines)


async def build_schema_context(database: Database) -> str:
    """
    Build a compact schema context string for grounding NL→SQL.

    For now this focuses on SQLite introspection. If introspection fails,
    falls back to a static schema summary.
    """
    # Keep the schema context compact: it gets injected into every LLM prompt.
    # If you later add many tables/columns, consider filtering/allowlisting here.
    url = str(getattr(database, "url", "") or "")
    if url in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[url]

    if "sqlite" not in url.lower():
        _SCHEMA_CACHE[url] = _fallback_schema()
        return _SCHEMA_CACHE[url]

    try:
        tables, columns_by_table, relationships = await _introspect_sqlite(database)
        value_hints = await _build_value_hints(database, tables)
        schema = _format_schema(
            tables, columns_by_table, relationships, value_hints=value_hints
        )
    except Exception:
        schema = _fallback_schema()

    _SCHEMA_CACHE[url] = schema
    return schema
