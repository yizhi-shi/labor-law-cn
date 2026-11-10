#!/usr/bin/env python3
"""Rebuild the corpus index from Markdown front matter.

    python3 scripts/build_index.py [--check]

Outputs
    data/index.json      machine-readable master index
    data/index.csv       spreadsheet-friendly flat table
    data/INDEX.md        human-readable table of contents
    data/articles/*.json per-document article split (第X条 -> text)
    data/stats.json      aggregate statistics

The script is idempotent: it recomputes sha256/chars/articles and writes them
back into the front matter when they differ, so `verify.py` always has a truth
source.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from docx2md import extract_articles, strip_front_matter  # noqa: E402

LEVEL_ORDER = ["法律", "行政法规", "司法解释", "部门规章", "地方性法规", "规范性文件", "修改废止决定"]
STATUS_ORDER = ["有效", "尚未生效", "已修改", "已废止"]
REQUIRED = ["id", "title", "level", "level_code", "issuer", "promulgated", "effective",
            "status", "status_code", "topics", "source", "source_name", "retrieved"]
TOPICS = ["劳动基准", "劳动合同", "集体合同与工会", "就业促进", "职业培训",
          "劳动安全卫生", "特殊群体保护", "社会保险", "工资保障", "劳动争议处理",
          "劳动保障监察", "新就业形态", "人事关系", "涉外用工", "综合/其他"]

# 年龄维度标签：覆盖“从童工到超龄/退休返聘”的全生命周期
AGE_RULES = [
    (("童工", "未满16", "未满十六", "禁止使用童工"), ["未满16岁（童工）"]),
    (("未成年工", "未成年"), ["16-18岁（未成年工）"]),
    (("女职工", "妇女权益", "生育保险", "产假", "女职工劳动保护"), ["育龄女性（孕期/产期/哺乳期）"]),
    (("超龄", "退休返聘", "已达法定退休年龄", "享受养老保险待遇"), ["超龄/退休返聘"]),
    (("退休", "退职", "延迟退休", "离休"), ["临近退休/退休"]),
    (("实习", "职业学校学生", "技工学校", "学徒", "职业教育"), ["在校生/实习生/学徒"]),
    (("残疾人",), ["残疾人"]),
    (("退役军人",), ["退役军人"]),
    (("就业促进", "高校毕业生", "青年就业", "就业服务"), ["青年劳动者"]),
    (("老年人", "高龄"), ["高龄劳动者"]),
]


def age_groups_for(fm: dict) -> list[str]:
    explicit = fm.get("age_groups")
    if explicit:
        return [a for a in explicit if a]
    text = fm.get("title", "") + " " + " ".join(fm.get("topics") or []) + " " + (fm.get("notes") or "")
    out: list[str] = []
    for keys, ages in AGE_RULES:
        if any(k in text for k in keys):
            for a in ages:
                if a not in out:
                    out.append(a)
    return out


def parse_md(path: Path) -> tuple[dict, str] | tuple[None, None]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    fm = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4:].lstrip("\n")
    return fm, body


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_front_matter(path: Path, fm: dict, body: str) -> None:
    path.write_text("---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
                    + "---\n\n" + body, encoding="utf-8")


def normalize_fm(fm: dict) -> dict:
    for k in ("title", "short_title", "issuer", "doc_number", "version_note", "notes",
              "province", "category"):
        fm.setdefault(k, "")
        if fm[k] is None:
            fm[k] = ""
    for key in ("promulgated", "effective", "retrieved"):
        v = fm.get(key)
        if isinstance(v, (date, datetime)):
            fm[key] = v.isoformat()
        elif v is not None:
            fm[key] = str(v)
    fm["promulgated"] = str(fm.get("promulgated") or "")
    fm["effective"] = str(fm.get("effective") or "")
    fm.setdefault("topics", [])
    fm["topics"] = [t for t in fm["topics"] if t] or ["综合/其他"]
    fm.setdefault("related", [])
    fm.setdefault("doc_type", fm.get("level", ""))
    return fm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="do not rewrite files")
    args = ap.parse_args()

    docs: list[dict] = []
    articles_dir = ROOT / "data" / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    files = sorted(p for p in (ROOT / "data").rglob("*.md")
                   if p.name != "INDEX.md" and "raw" not in p.parts)
    for path in files:
        fm, body = parse_md(path)
        if fm is None:
            errors.append(f"{path}: missing/invalid YAML front matter")
            continue
        fm = normalize_fm(fm)
        missing = [k for k in REQUIRED if not fm.get(k) and fm.get(k) != 0]
        if missing:
            errors.append(f"{path}: missing fields {missing}")
            continue
        arts = extract_articles(body)
        new_sha = sha256(body)
        changed = (fm.get("sha256") != new_sha or fm.get("chars") != len(re.sub(r"\s", "", body))
                   or fm.get("articles") != len(arts))
        fm["sha256"] = new_sha
        fm["chars"] = len(re.sub(r"\s", "", body))
        fm["articles"] = len(arts)
        if changed and not args.check:
            write_front_matter(path, fm, body)

        fm["age_groups"] = age_groups_for(fm)
        rec = {k: fm.get(k) for k in (
            "id", "title", "short_title", "level", "level_code", "issuer", "doc_number",
            "promulgated", "effective", "status", "status_code", "category", "doc_type",
            "province", "topics", "source", "source_name", "retrieved",
            "sha256", "chars", "articles", "version_group", "version_note", "related", "notes",
            "age_groups")}
        rec["path"] = str(path.relative_to(ROOT)).replace("\\", "/")
        docs.append(rec)

        art_path = articles_dir / f"{fm['id']}.json"
        payload = {"id": fm["id"], "title": fm["title"], "articles": arts}
        if not args.check:
            art_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # version groups -> related ids
    by_group: dict[str, list[str]] = defaultdict(list)
    for d in docs:
        if d.get("version_group"):
            by_group[d["version_group"]].append(d["id"])
    for d in docs:
        siblings = [i for i in by_group.get(d.get("version_group", ""), []) if i != d["id"]]
        d["related"] = sorted(set(list(d.get("related") or []) + siblings))

    docs.sort(key=lambda d: (LEVEL_ORDER.index(d["level"]) if d["level"] in LEVEL_ORDER else 99,
                             d.get("promulgated") or "", d["title"]))
    by_level = Counter(d["level"] for d in docs)
    by_status = Counter(d["status"] for d in docs)
    topic_counts = Counter(t for d in docs for t in d["topics"])
    age_counts = Counter(a for d in docs for a in d.get("age_groups", []))
    by_province = Counter(d["province"] for d in docs if d["province"])

    index = {
        "meta": {
            "name": "中国劳动法领域法规语料库",
            "generated_at": date.today().isoformat(),
            "source": "国家法律法规数据库 https://flk.npc.gov.cn 及人社部官网",
            "count": len(docs),
            "by_level": dict(by_level),
            "by_status": dict(by_status),
            "by_province": dict(by_province),
            "topics": dict(topic_counts),
            "age_groups": dict(age_counts),
            "levels": LEVEL_ORDER,
            "status_order": STATUS_ORDER,
        },
        "documents": docs,
    }
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "data" / "stats.json").write_text(
        json.dumps(index["meta"], ensure_ascii=False, indent=1), encoding="utf-8")

    with (ROOT / "data" / "index.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "short_title", "level", "status", "promulgated",
                    "effective", "issuer", "doc_number", "province", "topics",
                    "articles", "chars", "path", "source"])
        for d in docs:
            w.writerow([d["id"], d["title"], d["short_title"], d["level"], d["status"],
                        d["promulgated"], d["effective"], d["issuer"], d.get("doc_number", ""),
                        d.get("province", ""), "|".join(d["topics"]), d["articles"], d["chars"],
                        d["path"], d["source"]])

    # ---------------------------------------------------------------- INDEX.md
    lines = [
        "# 中国劳动法领域法规索引",
        "",
        f"> 共 **{len(docs)}** 篇 · 生成日期 {index['meta']['generated_at']} · "
        f"数据源：国家法律法规数据库、人力资源和社会保障部官网",
        "",
        "| 层级 | 数量 |",
        "|---|---|",
    ]
    for lv in LEVEL_ORDER:
        if by_level.get(lv):
            lines.append(f"| {lv} | {by_level[lv]} |")
    lines += ["", "## 按层级与效力状态", ""]
    for lv in LEVEL_ORDER:
        lv_docs = [d for d in docs if d["level"] == lv]
        if not lv_docs:
            continue
        lines += [f"### {lv}（{len(lv_docs)}）", ""]
        for status in STATUS_ORDER:
            st_docs = [d for d in lv_docs if d["status"] == status]
            if not st_docs:
                continue
            lines += [f"**{status}**", ""]
            for d in st_docs:
                extra = f" · {d['issuer']}" if d.get("issuer") else ""
                prov = f" · {d['province']}" if d.get("province") else ""
                lines.append(f"- [{d['title']}（{d['promulgated']}）]({d['path']})"
                             f" — {d['level']}{prov}{extra} · {d['articles']} 条")
            lines.append("")
    (ROOT / "data" / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"indexed {len(docs)} documents -> data/index.json, index.csv, INDEX.md")
    if errors:
        print(f"\n{len(errors)} errors:")
        for e in errors[:40]:
            print(" -", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
