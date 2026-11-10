#!/usr/bin/env python3
"""Restore the official effective date (施行日期) of the scraped version.

`fix_metadata.py` reads the date from the text's 附则, but for amended statutes
the 附则 keeps the *original* act's effective date, while flk records the date
the *current version* took effect.  This script prefers machine-readable
metadata over prose:

    flk detail cache  >  research/local/index.json  >  research/mohrss/index.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "research" / "flk_cache" / "detail"


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> None:
    official: dict[str, str] = {}

    for f in CACHE.glob("*.json"):
        d = load_json(f, {})
        if d.get("sxrq"):
            official[f.stem] = str(d["sxrq"])

    for row in load_json(ROOT / "research" / "local" / "index.json", []):
        if row.get("bbbs") and row.get("effective"):
            official.setdefault(row["bbbs"], str(row["effective"]))

    for row in load_json(ROOT / "research" / "mohrss" / "index.json", {}).get("items", []):
        if row.get("id") and row.get("effective"):
            official.setdefault(row["id"].replace("mohrss-", ""), str(row["effective"]))

    changed = 0
    for path in sorted((ROOT / "data").rglob("*.md")):
        if path.name == "INDEX.md" or "raw" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        fm = yaml.safe_load(text[3:end]) or {}
        doc_id = str(fm.get("id", ""))
        key = doc_id[4:] if doc_id.startswith("flk-") else doc_id
        new = official.get(key)
        if not new or new == fm.get("effective"):
            continue
        fm["effective"] = new
        path.write_text("---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
                        + "---\n\n" + text[end + 4:].lstrip("\n"), encoding="utf-8")
        changed += 1
    print(f"restored effective date for {changed} documents")


if __name__ == "__main__":
    sys.exit(main())
