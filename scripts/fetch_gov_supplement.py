#!/usr/bin/env python3
"""Add the few national labour regulations that the flk database does not carry.

flk.npc.gov.cn only stores the 1978/1981 National People's Congress approval
resolutions, not the actual 国务院 办法/规定 bodies.  We therefore take the full
text from the Beijing municipal government portal, which republishes the
official 国发 documents verbatim (including 发文字号 and 批准/施行信息).

Documents added
    data/administrative-regulations/关于安置老弱病残干部的暂行办法-1978.md
    data/administrative-regulations/国务院关于工人退休、退职的暂行办法-1978.md
    data/administrative-regulations/国务院关于职工探亲待遇的规定-1981.md
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw" / "gov"
OUT = ROOT / "data" / "administrative-regulations"
RETRIEVED = "2026-11-10"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

SOURCES = {
    "1978": "https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/202509/t20250929_4214107.html",
    "1981": "https://www.beijing.gov.cn/zhengce/zfwj/zfwj/szfwj/201905/t20190523_70552.html",
}


def fetch(url: str, name: str) -> str:
    import urllib.request

    RAW.mkdir(parents=True, exist_ok=True)
    cache = RAW / f"{name}.html"
    if cache.exists() and cache.stat().st_size > 5000:
        return cache.read_text(encoding="utf-8", errors="replace")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")
    cache.write_text(html, encoding="utf-8")
    return html


def paragraphs(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    box = None
    for cand in soup.find_all("div"):
        classes = " ".join(cand.get("class") or [])
        if "mainText" in classes or cand.get("id") == "mainText":
            box = cand
            break
    if box is None:
        raise RuntimeError("mainText container not found")
    ps: list[str] = []
    for p in box.find_all(["p", "div"], recursive=True):
        t = p.get_text("\n", strip=True).replace("\xa0", " ").strip()
        t = re.sub(r"[ \t]+", " ", t)
        if t:
            ps.append(t)
    # first two paragraphs are a hidden duplicate of the whole article
    return ps[2:]


def build_md(title: str, citation: str, intro: list[str], articles: list[str]) -> str:
    body = [f"# {title}", "", citation, ""]
    if intro:
        body += intro + [""]
    body += articles
    md = "\n\n".join(x for x in body if x is not None).strip() + "\n"
    return re.sub(r"\n{3,}", "\n\n", md)


def write_doc(path: Path, fm: dict, md: str) -> None:
    order = ["id", "title", "short_title", "level", "level_code", "issuer", "doc_number",
             "promulgated", "effective", "status", "status_code", "category", "doc_type",
             "province", "topics", "source", "source_name", "retrieved", "sha256", "chars",
             "articles", "version_group", "version_note", "related", "notes"]
    fm = {**{k: fm.get(k, "") for k in order}, **fm}
    if not fm.get("version_group"):
        fm["version_group"] = fm.get("title", "")
    for k in order:
        if k in fm:
            fm[k] = fm.pop(k)
    fm["sha256"] = hashlib.sha256(md.encode("utf-8")).hexdigest()
    fm["chars"] = len(re.sub(r"\s", "", md))
    fm["articles"] = len(re.findall(r"(?m)^第[一二三四五六七八九十百零〇两]+条", md))
    text = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + md
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.name} ({fm['articles']} articles, {fm['chars']} chars)")


def main() -> None:
    html78 = fetch(SOURCES["1978"], "guowuyuan-1978-104")
    ps78 = paragraphs(html78)
    i1 = ps78.index("附件一")
    i2 = ps78.index("附件二")

    # 附件一：关于安置老弱病残干部的暂行办法
    block = ps78[i1 + 1: i2]
    title_a = block[0]
    cite_a = block[1]
    intro_a = [x for x in block[2:] if not re.match(r"^第[一二三四五六七八九十]+条", x)
               and not x.startswith("（")]
    arts_a = [x for x in block[2:] if re.match(r"^第[一二三四五六七八九十]+条", x)]
    # multi-line article bodies: paragraphs starting with （一） belong to previous article
    arts_a_full: list[str] = []
    for x in block[2:]:
        if re.match(r"^第[一二三四五六七八九十]+条", x):
            arts_a_full.append(x)
        elif arts_a_full and (x.startswith("（") or x.startswith("第")) and len(x) > 2:
            arts_a_full[-1] += "\n" + x
    md_a = build_md(title_a, cite_a,
                    [x for x in block[2:] if not re.match(r"^第[一二三四五六七八九十]+条", x)
                     and not x.startswith("（")][:2],
                    arts_a_full)

    # 附件二：国务院关于工人退休、退职的暂行办法
    block = ps78[i2 + 1:]
    title_b = "国务院" + block[0]
    cite_b = block[1]
    arts_b: list[str] = []
    intro_b: list[str] = []
    for x in block[2:]:
        if re.match(r"^第[一二三四五六七八九十]+条", x):
            arts_b.append(x)
        elif arts_b and (x.startswith("（") or x.startswith("第")):
            arts_b[-1] += "\n" + x
        elif not arts_b:
            intro_b.append(x)
    md_b = build_md(title_b, cite_b, intro_b, arts_b)

    html81 = fetch(SOURCES["1981"], "guowuyuan-1981-36")
    ps81 = paragraphs(html81)
    start = next(i for i, x in enumerate(ps81) if x.startswith("附:国务院关于职工探亲待遇的规定"))
    end = next(i for i, x in enumerate(ps81) if "北京市人民政府贯彻执行" in x and i > start)
    block = [x for x in ps81[start + 1: end] if x and x != "国务院关于职工探亲待遇的规定"]
    cite = ("（1981年3月6日第五届全国人民代表大会常务委员会第十七次会议批准，"
            "1981年3月14日国务院发布，自发布之日起施行）")
    arts_c: list[str] = []
    intro_c: list[str] = []
    for x in block:
        if re.match(r"^第[一二三四五六七八九十]+条", x):
            arts_c.append(x)
        elif arts_c and (x.startswith("（") or x.startswith("(")):
            arts_c[-1] += "\n" + x
        elif not arts_c:
            intro_c.append(x)
    md_c = build_md("国务院关于职工探亲待遇的规定", cite, intro_c, arts_c)

    common = dict(level="行政法规", level_code=2, issuer="国务院",
                  status="有效", status_code=3, category="社会法",
                  doc_type="行政法规", province="", source_name="北京市人民政府门户网站（转发国务院文件）",
                  retrieved=RETRIEVED, related=[], version_note="")
    write_doc(OUT / "关于安置老弱病残干部的暂行办法-1978.md", {
        **common, "id": "gov-1978-anzhi", "title": "关于安置老弱病残干部的暂行办法",
        "short_title": "安置老弱病残干部暂行办法", "doc_number": "国发〔1978〕104号",
        "promulgated": "1978-06-02", "effective": "1978-06-02",
        "topics": ["社会保险", "人事关系"], "source": SOURCES["1978"],
        "notes": "国发〔1978〕104号通知附件一；flk 未收录正文。部分内容已被社会保险法及后续退休制度改革取代，引用时注意。",
    }, md_a)
    write_doc(OUT / "国务院关于工人退休、退职的暂行办法-1978.md", {
        **common, "id": "gov-1978-tuixiu", "title": "国务院关于工人退休、退职的暂行办法",
        "short_title": "工人退休退职暂行办法", "doc_number": "国发〔1978〕104号",
        "promulgated": "1978-06-02", "effective": "1978-06-02",
        "topics": ["社会保险"], "source": SOURCES["1978"],
        "notes": "国发〔1978〕104号通知附件二；flk 未收录正文。退休年龄、退休费等内容已被社会保险法及2024年渐进式延迟退休决定大幅取代，仅作历史与衔接参考。",
    }, md_b)
    write_doc(OUT / "国务院关于职工探亲待遇的规定-1981.md", {
        **common, "id": "gov-1981-tanqin", "title": "国务院关于职工探亲待遇的规定",
        "short_title": "职工探亲待遇规定", "doc_number": "国发〔1981〕36号",
        "promulgated": "1981-03-14", "effective": "1981-03-14",
        "topics": ["劳动基准"], "source": SOURCES["1981"],
        "notes": "flk 未收录正文，仅有全国人大批准决议。原文见国务院国发〔1981〕36号；北京市实施细则等地方细则未收录。",
    }, md_c)


if __name__ == "__main__":
    sys.exit(main())
