#!/usr/bin/env python3
"""Full-text search over the labour-law corpus (stdlib only).

Examples
    python3 scripts/search.py 加班费 --status 有效
    python3 scripts/search.py 竞业限制 经济补偿 --level 法律 --limit 5
    python3 scripts/search.py 工伤 --topic 社会保险 --snippets 2
    python3 scripts/search.py --doc 劳动合同法 --article 39
    python3 scripts/search.py --list --level 行政法规
    python3 scripts/search.py --stats
    python3 scripts/search.py 拖欠工资 --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INDEX = DATA / "index.json"


def load_index() -> dict:
    if not INDEX.exists():
        sys.exit("data/index.json 不存在，请先运行 python3 scripts/build_index.py")
    return json.loads(INDEX.read_text(encoding="utf-8"))


def load_articles(doc_id: str) -> list[dict]:
    p = DATA / "articles" / f"{doc_id}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("articles", [])


def snippet(text: str, term: str, width: int = 80) -> str:
    i = text.find(term)
    if i == -1:
        return text[: width * 2].replace("\n", " ")
    start = max(0, i - width)
    end = min(len(text), i + len(term) + width)
    s = text[start:end].replace("\n", " ")
    return ("…" if start > 0 else "") + s + ("…" if end < len(text) else "")


def score_doc(doc: dict, terms: list[str], mode: str) -> tuple[float, list[dict]]:
    title = doc["title"] + " " + doc.get("short_title", "")
    score = 0.0
    hits: list[dict] = []
    title_hit = sum(1 for t in terms if t in title)
    if mode == "all" and title_hit == 0:
        pass
    score += title_hit * 25
    for t in terms:
        if t in " ".join(doc.get("topics", [])):
            score += 6
    if doc.get("status") == "有效":
        score += 2
    arts = load_articles(doc["id"])
    matched_terms = 0
    for term in terms:
        found = 0
        for a in arts:
            n = a["text"].count(term)
            if n:
                found += n
                if len(hits) < 20:
                    hits.append({"no": a["no"], "chapter": a.get("chapter", ""),
                                 "snippet": snippet(a["text"], term)})
        if found:
            matched_terms += 1
            score += min(found, 15) * 2.0
    if len(terms) > 1:
        score += matched_terms * 8
    return score, hits


def filter_docs(docs: list[dict], args) -> list[dict]:
    out = []
    for d in docs:
        if args.level and d["level"] != args.level:
            continue
        if args.status and d["status"] != args.status:
            continue
        if args.topic and args.topic not in d.get("topics", []):
            continue
        if args.province and d.get("province") != args.province:
            continue
        if args.age and not any(args.age in a for a in d.get("age_groups", [])):
            continue
        if args.year and not (d.get("promulgated", "").startswith(args.year)
                              or d.get("effective", "").startswith(args.year)):
            continue
        out.append(d)
    return out


def print_doc(doc: dict) -> None:
    print(f"{doc['title']}")
    print(f"  id: {doc['id']}  层级: {doc['level']}  状态: {doc['status']}")
    print(f"  制定机关: {doc.get('issuer','')}  公布: {doc.get('promulgated','')}  "
          f"施行: {doc.get('effective','')}")
    if doc.get("province"):
        print(f"  省份: {doc['province']}")
    print(f"  主题: {', '.join(doc.get('topics', []))}  条文: {doc.get('articles', 0)} 条  "
          f"字数: {doc.get('chars', 0)}")
    print(f"  文件: {doc['path']}")
    print(f"  来源: {doc['source']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="劳动法语料库检索")
    ap.add_argument("query", nargs="*", help="检索关键词（空格分隔，默认 AND）")
    ap.add_argument("--level", choices=["法律", "行政法规", "司法解释", "部门规章",
                                        "地方性法规", "规范性文件", "修改废止决定"])
    ap.add_argument("--status", choices=["有效", "尚未生效", "已修改", "已废止"])
    ap.add_argument("--topic")
    ap.add_argument("--province")
    ap.add_argument("--age", help="年龄维度：未满16 / 16-18 / 育龄女性 / 超龄 / 临近退休 / 在校生 / 残疾人 / 退役军人 / 青年 / 高龄")
    ap.add_argument("--year")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--snippets", type=int, default=3, help="每篇展示的条文片段数")
    ap.add_argument("--any", action="store_true", help="任一关键词命中即可（默认全部命中）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--doc", help="按 id 或标题查单篇")
    ap.add_argument("--article", help="配合 --doc 查指定条号，如 39 或 第三十九条")
    ap.add_argument("--list", action="store_true", help="列出筛选后的文件，不检索")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--topics", action="store_true")
    args = ap.parse_args()

    index = load_index()
    docs = index["documents"]
    if not args.query and (args.age or args.province or args.level or args.status or args.topic):
        args.list = True

    if args.stats:
        print(json.dumps(index["meta"], ensure_ascii=False, indent=2))
        return
    if args.topics:
        for t, n in sorted(index["meta"].get("topics", {}).items(), key=lambda x: -x[1]):
            print(f"{n:>5}  {t}")
        print("\n年龄维度：")
        for t, n in sorted(index["meta"].get("age_groups", {}).items(), key=lambda x: -x[1]):
            print(f"{n:>5}  {t}")
        return
    if args.list:
        order = {"有效": 0, "尚未生效": 1, "已修改": 2, "已废止": 3}
        rows = sorted(filter_docs(docs, args),
                      key=lambda d: (order.get(d["status"], 9), d.get("promulgated") or ""),
                      reverse=False)
        rows = sorted(rows, key=lambda d: order.get(d["status"], 9))
        rows = sorted(rows, key=lambda d: d.get("promulgated") or "", reverse=True)
        rows = sorted(rows, key=lambda d: order.get(d["status"], 9))
        for d in rows[: args.limit if args.limit else None]:
            print(f"[{d['status']}] {d['promulgated']} {d['title']}  ({d['path']})")
        return
    if args.doc:
        cand = [d for d in docs if d["id"] == args.doc]
        if not cand:
            cand = [d for d in docs if args.doc in d["title"]]
        if not cand:
            sys.exit(f"未找到：{args.doc}")
        doc = cand[0]
        print_doc(doc)
        arts = load_articles(doc["id"])
        if args.article:
            want = args.article
            num = int(want) if want.isdigit() else None
            for a in arts:
                if (num is not None and a["n"] == num) or a["no"] == want:
                    print(f"\n{a['no']} {a.get('chapter','')}\n{a['text']}")
                    return
            sys.exit(f"未找到第 {args.article} 条")
        print(f"\n目录（{len(arts)} 条）：")
        last_chapter = ""
        for a in arts:
            if a.get("chapter") and a["chapter"] != last_chapter:
                print(f"  {a['chapter']}")
                last_chapter = a["chapter"]
            print(f"    {a['no']}")
        return

    terms = [t for t in args.query if t.strip()]
    if not terms:
        ap.error("请提供检索关键词，或使用 --doc/--stats/--topics/--list")
    docs = filter_docs(docs, args)
    ranked = []
    for d in docs:
        s, hits = score_doc(d, terms, "any" if args.any else "all")
        if s <= 0:
            continue
        if not args.any:
            arts_text = " ".join(a["text"] for a in load_articles(d["id"]))
            title = d["title"] + d.get("short_title", "")
            if not all((t in arts_text) or (t in title) for t in terms):
                continue
        ranked.append((s, d, hits))
    ranked.sort(key=lambda x: (-x[0], x[1]["promulgated"] or ""))
    ranked = ranked[: args.limit]

    if args.json:
        out = [{"score": round(s, 1), **{k: d[k] for k in (
            "id", "title", "level", "status", "promulgated", "effective",
            "province", "topics", "path", "source")}, "hits": h[: args.snippets]}
            for s, d, h in ranked]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if not ranked:
        print("未找到匹配文件。可尝试更短的关键词、--any，或放宽 --level/--status 过滤。")
        return
    for i, (s, d, hits) in enumerate(ranked, 1):
        print(f"\n[{i}] {d['title']}  —— {d['level']} / {d['status']} / "
              f"{d['promulgated']}" + (f" / {d['province']}" if d.get("province") else ""))
        print(f"    {d['path']}  ·  {d['source']}")
        for h in hits[: args.snippets]:
            print(f"    · {h['no']}（{h['chapter']}）{h['snippet']}")


if __name__ == "__main__":
    main()
