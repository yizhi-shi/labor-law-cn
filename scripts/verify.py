#!/usr/bin/env python3
"""Verify corpus integrity: front matter, hashes, article counts, coverage.

    python3 scripts/verify.py            # human report
    python3 scripts/verify.py --strict   # non-zero exit on warnings too

Checks
    1. every indexed file exists and sha256 matches its body
    2. required front-matter fields and enum values are valid
    3. no duplicate ids, no empty/placeholder documents
    4. article json exists and matches front matter count
    5. a curated list of core labour statutes is present and effective
    6. source URLs point at official domains
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

CORE = [
    ("中华人民共和国劳动法", "有效"),
    ("中华人民共和国劳动合同法", "有效"),
    ("中华人民共和国就业促进法", "有效"),
    ("中华人民共和国劳动争议调解仲裁法", "有效"),
    ("中华人民共和国社会保险法", "有效"),
    ("中华人民共和国工会法", "有效"),
    ("中华人民共和国安全生产法", "有效"),
    ("中华人民共和国职业病防治法", "有效"),
    ("工伤保险条例", "有效"),
    ("失业保险条例", "有效"),
    ("劳动保障监察条例", "有效"),
    ("职工带薪年休假条例", "有效"),
    ("女职工劳动保护特别规定", "有效"),
    ("中华人民共和国劳动合同法实施条例", "有效"),
    ("保障农民工工资支付条例", "有效"),
]

OFFICIAL_HOSTS = ("flk.npc.gov.cn", "mohrss.gov.cn", "gov.cn", "court.gov.cn", "spp.gov.cn")
BAD_MARKERS = ["系统异常", "Please enable JavaScript", "Index of /", "404 Not Found"]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    strict = "--strict" in sys.argv
    index_path = DATA / "index.json"
    if not index_path.exists():
        sys.exit("data/index.json 缺失，先运行 python3 scripts/build_index.py")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    docs = index["documents"]
    errors: list[str] = []
    warnings: list[str] = []

    ids: set[str] = set()
    for d in docs:
        path = ROOT / d["path"]
        if d["id"] in ids:
            errors.append(f"duplicate id: {d['id']}")
        ids.add(d["id"])
        if not path.exists():
            errors.append(f"missing file: {d['path']}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            errors.append(f"{d['path']}: no front matter")
            continue
        end = text.find("\n---", 3)
        body = text[end + 4:].lstrip("\n")
        if sha256(body) != d["sha256"]:
            errors.append(f"{d['path']}: sha256 mismatch (run build_index.py)")
        if len(re.sub(r"\s", "", body)) < 100:
            errors.append(f"{d['path']}: body too short")
        for m in BAD_MARKERS:
            if m in body:
                errors.append(f"{d['path']}: contains placeholder/error marker {m!r}")
        if d["status"] not in ("有效", "已修改", "已废止", "尚未生效"):
            errors.append(f"{d['path']}: invalid status {d['status']!r}")
        if d["level"] not in ("法律", "行政法规", "司法解释", "部门规章", "地方性法规", "规范性文件", "修改废止决定"):
            errors.append(f"{d['path']}: invalid level {d['level']!r}")
        if not d["source"].startswith("https://"):
            errors.append(f"{d['path']}: source is not https")
        elif not any(h in d["source"] for h in OFFICIAL_HOSTS):
            warnings.append(f"{d['path']}: non-official source host {d['source']}")
        ap = DATA / "articles" / f"{d['id']}.json"
        if not ap.exists():
            warnings.append(f"{d['path']}: no article split file")
        else:
            arts = json.loads(ap.read_text(encoding="utf-8")).get("articles", [])
            if len(arts) != d["articles"]:
                warnings.append(f"{d['path']}: article json ({len(arts)}) != index ({d['articles']})")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d.get("promulgated") or ""):
            warnings.append(f"{d['path']}: bad promulgated date {d.get('promulgated')!r}")

    current = {(d["title"], d["status"]) for d in docs}
    titles_current = {d["title"] for d in docs if d["status"] in ("有效", "尚未生效")}
    for title, want in CORE:
        if (title, want) not in current:
            if title in titles_current:
                continue
            errors.append(f"CORE MISSING: {title} (status {want})")

    # duplicate title+promulgated
    seen = set()
    for d in docs:
        key = (d["title"], d["promulgated"])
        if key in seen:
            warnings.append(f"duplicate title/date: {key}")
        seen.add(key)

    by_level: dict[str, int] = {}
    for d in docs:
        by_level[d["level"]] = by_level.get(d["level"], 0) + 1

    print(f"documents: {len(docs)}")
    for k, v in sorted(by_level.items(), key=lambda x: -x[1]):
        print(f"  {k:8s} {v}")
    print(f"articles:  {sum(d['articles'] for d in docs)} 条")
    print(f"chars:     {sum(d['chars'] for d in docs):,}")
    print(f"topics:    {', '.join(index['meta'].get('topics', {}).keys())}")
    if warnings:
        print(f"\nwarnings ({len(warnings)}):")
        for w in warnings[:30]:
            print("  -", w)
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors[:50]:
            print("  -", e)
        sys.exit(1)
    if strict and warnings:
        sys.exit(2)
    print("\nOK: corpus integrity verified")


if __name__ == "__main__":
    main()
