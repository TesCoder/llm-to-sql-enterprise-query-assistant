from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


@dataclass(frozen=True)
class Preset:
    id: str
    canonical: str
    sql: str


def normalize_question(text: str) -> str:
    """
    Normalize user questions so simple phrasing differences match presets.

    Strategy: lowercase, remove punctuation, collapse whitespace.
    """
    lowered = text.strip().lower()
    without_punct = _PUNCT_RE.sub(" ", lowered)
    collapsed = _WHITESPACE_RE.sub(" ", without_punct).strip()
    return collapsed


def _as_str_list(value: Any) -> Sequence[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        # Allow a single alias as a string for convenience.
        return [value] if value.strip() else []
    return []


def load_preset_index(json_path: Path) -> Dict[str, Preset]:
    """
    Load presets from a JSON file into a dict for fast lookup.

    Supported JSON shapes:
      1) List of objects:
         [
           {"id":"...", "canonical":"...", "aliases":[...], "sql":"..."}
         ]
      2) Object keyed by id:
         {
           "preset_id": {"canonical":"...", "aliases":[...], "sql":"..."}
         }
    """
    index: Dict[str, Preset] = {}
    if not json_path.exists():
        return index

    with json_path.open(encoding="utf-8") as fp:
        raw = json.load(fp)

    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        items = [x for x in raw if isinstance(x, dict)]
    elif isinstance(raw, dict):
        for preset_id, obj in raw.items():
            if not isinstance(obj, dict):
                continue
            merged = {"id": preset_id, **obj}
            items.append(merged)
    else:
        return index

    for row in items:
        preset_id = str(row.get("id") or "").strip()
        canonical = str(row.get("canonical") or "").strip()
        sql = str(row.get("sql") or "").strip()
        aliases = _as_str_list(row.get("aliases"))
        enabled = row.get("enabled", True)

        if enabled is False:
            continue
        if not preset_id or not canonical or not sql:
            continue

        preset = Preset(id=preset_id, canonical=canonical, sql=sql)

        phrases = [canonical, *aliases]
        for phrase in phrases:
            key = normalize_question(str(phrase))
            if key:
                index[key] = preset

    return index


def match_preset(index: Dict[str, Preset], question: str) -> Optional[Preset]:
    key = normalize_question(question)
    return index.get(key)

