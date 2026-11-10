#!/usr/bin/env python3
"""Convert an official .docx statute into normalized GitHub-flavoured Markdown.

The National Laws and Regulations Database ships each document as .docx.  Raw
pandoc output is decent but inconsistent: chapter headings are plain
paragraphs, there are stray escaping backslashes and BOMs, and indentation
spaces differ between documents.  `convert_docx()` normalises the layout while
keeping every character of the official text.

CLI:
    python3 scripts/docx2md.py input.docx output.md [--title 标题]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

CH_CHAPTER = re.compile(r"^(第[一二三四五六七八九十百零〇两]+编)([\s　].*)?$")
CH_SECTION = re.compile(r"^(第[一二三四五六七八九十百零〇两]+节)([\s　].*)?$")
CH_CHAPTER_ONLY = re.compile(r"^第[一二三四五六七八九十百零〇两]+章")
CH_SECTION_ONLY = re.compile(r"^第[一二三四五六七八九十百零〇两]+节")
CH_ARTICLE = re.compile(r"^(第[一二三四五六七八九十百零〇两]+条)(?=[\s　]|$)")
CH_CN_NUM = re.compile(r"^[一二三四五六七八九十百千零〇两]+$")

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def cn2int(s: str) -> int:
    """Translate a Chinese numeral (<= 9999) into an int. 第十条 -> 10."""
    total = section = 0
    num = 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            if num == 0:
                num = 1
            section += num * unit
            num = 0
        else:
            raise ValueError(f"not a numeral: {s}")
    return total + section + num


def pandoc_to_markdown(docx: Path) -> str:
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as tmp:
        out = tmp.name
    try:
        subprocess.run(
            ["pandoc", str(docx), "-t", "gfm", "--wrap=none", "-o", out],
            check=True,
            capture_output=True,
        )
        return Path(out).read_text(encoding="utf-8", errors="replace")
    finally:
        Path(out).unlink(missing_ok=True)


def normalize(raw: str, title: str = "") -> str:
    text = raw.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]

    # Drop pandoc's leading metadata / empty heading duplicates.
    out: list[str] = []
    has_bian = any(CH_CHAPTER_ONLY.match(ln.strip()) for ln in lines)
    for ln in lines:
        s = ln.strip()
        # 目录中的条目形如 "> 第一章　总　　则"，保持原样
        if s.startswith(">"):
            out.append(ln)
            continue
        if s:
            ln = ln.lstrip(" \t　")
        if has_bian and CH_CHAPTER_ONLY.match(s):
            out.append(f"## {s}")
            continue
        if has_bian and CH_SECTION_ONLY.match(s):
            out.append(f"#### {s}")
            continue
        if CH_CHAPTER_ONLY.match(s):
            out.append(f"## {s}")
            continue
        if CH_SECTION_ONLY.match(s):
            out.append(f"### {s}")
            continue
        out.append(ln)

    # Collapse >2 blank lines, strip trailing whitespace, drop leading blanks.
    cleaned: list[str] = []
    blank = 0
    for ln in out:
        if ln.strip() == "":
            blank += 1
            if blank > 1:
                continue
            cleaned.append("")
        else:
            blank = 0
            cleaned.append(ln)
    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    body = "\n".join(cleaned)
    body = re.sub(r"\\\n", "\n", body)  # lone pandoc line escapes
    body = re.sub(r"\n{3,}", "\n\n", body)

    if not body.lstrip().startswith("# "):
        heading = f"# {title}" if title else "# 法规全文"
        body = heading + "\n\n" + body
    # official docx usually repeats the title right below the (auto) heading
    lines = body.split("\n")
    if lines and lines[0].startswith("# ") and title:
        for i in range(1, min(4, len(lines))):
            if lines[i].strip() == "":
                continue
            if lines[i].strip() == title or lines[i].strip() == lines[0][2:].strip():
                lines.pop(i)
            break
        body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip() + "\n"


def convert_docx(docx: str | Path, out_md: str | Path | None = None, title: str = "") -> str:
    md = normalize(pandoc_to_markdown(Path(docx)), title=title)
    if out_md:
        Path(out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(out_md).write_text(md, encoding="utf-8")
    return md


# --------------------------------------------------------------------- articles
def extract_articles(md: str) -> list[dict]:
    """Split a normalized statute into articles with chapter/section context."""
    body = md
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4 :]

    articles: list[dict] = []
    chapter = section = ""
    cur: dict | None = None
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            if cur is not None and cur["paragraphs"] and cur["paragraphs"][-1] != "":
                cur["paragraphs"].append("")
            continue
        if line.startswith(">") or line.startswith("!["):
            continue
        stripped = line.lstrip("#").strip()
        if CH_CHAPTER_ONLY.match(stripped) and not CH_ARTICLE.match(stripped):
            if cur is not None:
                articles.append(cur)
                cur = None
            chapter, section = stripped, ""
            continue
        if CH_SECTION_ONLY.match(stripped):
            if cur is not None:
                articles.append(cur)
                cur = None
            section = stripped
            continue
        m = CH_ARTICLE.match(line)
        if m:
            if cur is not None:
                articles.append(cur)
            no = m.group(1)
            num_txt = no[1:-1]
            try:
                n = cn2int(num_txt)
            except ValueError:
                n = 0
            cur = {
                "no": no,
                "n": n,
                "chapter": chapter,
                "section": section,
                "paragraphs": [line[len(no):].strip()],
                "text": "",
            }
            continue
        if cur is not None:
            if line.startswith("#"):
                continue
            cur["paragraphs"].append(line)
    if cur is not None:
        articles.append(cur)

    for a in articles:
        paras = [p for p in a.pop("paragraphs") if p]
        a["text"] = "\n".join(paras)
        a["char_count"] = len(a["text"].replace("\n", ""))
    return [a for a in articles if a["text"]]


def strip_front_matter(md: str) -> str:
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            return md[end + 4 :].lstrip("\n")
    return md


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--title", default="")
    args = ap.parse_args()
    md = convert_docx(args.input, args.output, title=args.title)
    arts = extract_articles(md)
    print(f"wrote {args.output} ({len(md)} chars, {len(arts)} articles)")


if __name__ == "__main__":
    main()
