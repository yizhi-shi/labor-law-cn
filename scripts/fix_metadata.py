#!/usr/bin/env python3
"""Repair common metadata problems found by the coverage audit.

1. split articles that were merged into one paragraph by a broken docx line break
   (only when the numbers are strictly increasing, to avoid splitting inline
   references such as “本条例第三条”);
2. correct `effective` from the official “自YYYY年M月D日起施行” clause when the
   scraper had to fall back to the promulgation date;
3. add a short repeal note to `已废止` documents that have no note;
4. normalise YAML dates to ISO strings.

Run before build_index.py, then rebuild:

    python3 scripts/fix_metadata.py
    python3 scripts/build_index.py
    python3 scripts/verify.py
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from docx2md import cn2int  # noqa: E402

ARTICLE = re.compile(r"第[一二三四五六七八九十百零〇两]+条")
NUM_PREFIX = re.compile(r"^(\d{1,3})[.、]\s*(\S.{3,})")
CN_DIGITS = "零一二三四五六七八九"


def int2cn(n: int) -> str:
    if n <= 10:
        return "十" if n == 10 else CN_DIGITS[n]
    if n < 20:
        return "十" + CN_DIGITS[n % 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        return CN_DIGITS[tens] + "十" + (CN_DIGITS[ones] if ones else "")
    hundreds, rem = divmod(n, 100)
    return CN_DIGITS[hundreds] + "百" + (int2cn(rem) if rem else "")
EFFECTIVE = re.compile(
    r"(?:自|从)\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起\s*(?:施行|实施|执行)"
)
FROM_PUBLICATION = re.compile(r"自(?:公布|发布|颁布)之日起\s*(?:施行|实施|执行)")

REPEAL_NOTES = [
    (r"最高人民法院关于审理劳动争议案件适用法律若干问题的解释",
     "已被《最高人民法院关于审理劳动争议案件适用法律问题的解释（一）》（法释〔2020〕26号）废止或整合，仅作历史参考。"),
    (r"最高人民法院关于解除劳动合同的劳动争议仲裁申请期限",
     "已被《最高人民法院关于审理劳动争议案件适用法律问题的解释（一）》（法释〔2020〕26号）废止，仅作历史参考。"),
    (r"劳动保险条例", "1995年《劳动法》实施后多数内容已被取代，后经国务院文件清理废止，仅作历史参考。"),
]


def split_articles(body: str) -> tuple[str, int]:
    out: list[str] = []
    splits = 0
    last_n = 0
    for line in body.split("\n"):
        m_num = NUM_PREFIX.match(line)
        if m_num and last_n and int(m_num.group(1)) == last_n + 1 and not line.startswith(" "):
            line = f"第{int2cn(int(m_num.group(1)))}条 {m_num.group(2)}"
        am = ARTICLE.match(line)
        if am:
            tail = line[am.end(): am.end() + 2]
            if tail.startswith(("的", "规定", "之", "、", "和", "及")):
                am = None  # 这是上一条的引用续行，不是新条
        if am:
            try:
                last_n = cn2int(am.group()[1:-1])
            except ValueError:
                pass
        ms = list(ARTICLE.finditer(line))
        cuts: list[int] = []
        for m in ms:
            try:
                n = cn2int(m.group()[1:-1])
            except ValueError:
                continue
            after = line[m.end():]
            if not last_n or n != last_n + 1:
                continue
            if after.startswith(("规定", "、", "和", "及", "至", "之", "所", "的")):
                continue
            if len(after.strip()) < 8:
                continue
            cuts.append(m.start())
            last_n = n
        if not cuts:
            out.append(line)
            continue
        segments: list[str] = []
        start = 0
        for c in cuts:
            segments.append(line[start:c].strip())
            start = c
        segments.append(line[start:].strip())
        for i, seg in enumerate(segments):
            if not seg:
                continue
            if i > 0 and out and out[-1] != "":
                out.append("")
            out.append(seg)
        splits += 1
    return "\n".join(out), splits


def fix_front_matter(fm: dict, body: str) -> tuple[dict, str, list[str]]:
    changes: list[str] = []
    for key in ("promulgated", "effective", "retrieved"):
        v = fm.get(key)
        if isinstance(v, (date, datetime)):
            fm[key] = v.isoformat()

    # 1) effective date from the official clause
    dates = []
    for m in EFFECTIVE.finditer(body):
        y, mo, d = (int(x) for x in m.groups())
        try:
            dates.append(date(y, mo, d).isoformat())
        except ValueError:
            continue
    current = str(fm.get("effective") or "")
    promulgated = str(fm.get("promulgated") or "")
    if dates:
        official = dates[-1]
        if official != current:
            fm["effective"] = official
            changes.append(f"effective {current} -> {official}")
    elif FROM_PUBLICATION.search(body) and promulgated and current != promulgated:
        fm["effective"] = promulgated
        changes.append(f"effective {current} -> {promulgated} (from publication)")

    # 2) repeal note
    if fm.get("status") == "已废止" and not (fm.get("notes") or "").strip():
        note = "已废止（官方时效性标注），仅作历史参考；具体废止依据以官方公布为准。"
        for pattern, text in REPEAL_NOTES:
            if re.search(pattern, fm.get("title", "")):
                note = text
                break
        fm["notes"] = note
        changes.append("added repeal note")

    return fm, body, changes


def main() -> None:
    total_splits = 0
    changed_files = 0
    for path in sorted((ROOT / "data").rglob("*.md")):
        if path.name == "INDEX.md" or "raw" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        fm = yaml.safe_load(text[3:end]) or {}
        body = text[end + 4:].lstrip("\n")

        body, splits = split_articles(body)
        fm, body, changes = fix_front_matter(fm, body)
        if splits:
            changes.append(f"split {splits} merged article line(s)")
        if not changes:
            continue
        total_splits += splits
        changed_files += 1
        ordered = {}
        for k in ("id", "title", "short_title", "level", "level_code", "issuer",
                  "doc_number", "promulgated", "effective", "status", "status_code",
                  "category", "doc_type", "province", "topics", "age_groups", "source",
                  "source_name", "retrieved", "sha256", "chars", "articles",
                  "version_group", "version_note", "related", "notes"):
            if k in fm:
                ordered[k] = fm[k]
        for k in fm:
            ordered.setdefault(k, fm[k])
        path.write_text("---\n" + yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False)
                        + "---\n\n" + body, encoding="utf-8")

    print(f"updated {changed_files} files, split {total_splits} merged article lines")


if __name__ == "__main__":
    main()
