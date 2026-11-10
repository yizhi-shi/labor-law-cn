#!/usr/bin/env python3
"""National-level labour-law corpus builder (法律 / 行政法规 / 司法解释 / 决定).

Pipeline per document
    1. list row (bbbs, 时效性, 公布/施行日期) from the official search API
    2. detail (制定机关, 目录树, OSS 路径)
    3. download official .docx -> raw/flk/<bbbs>.docx
    4. convert -> normalised Markdown + YAML front matter -> data/<dir>/
    5. record everything in data/manifest.json

Selection is an explicit allow-list of official titles in ``SELECTION`` below;
every version returned by flk for a selected title is kept (so the corpus
contains the amendment history as well as the current text).

Usage
    python3 scripts/fetch_national.py --list          # dry run, show matches
    python3 scripts/fetch_national.py                 # fetch everything
    python3 scripts/fetch_national.py --only laws     # one group
    python3 scripts/fetch_national.py --refresh       # ignore caches
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from docx2md import convert_docx, extract_articles  # noqa: E402
from flk_client import FlkClient, SXX, clean_title  # noqa: E402

RETRIEVED = date.today().isoformat()
CACHE = ROOT / "research" / "flk_cache"

# ---------------------------------------------------------------------------
# Selection (official full titles as they appear in 国家法律法规数据库)
# ---------------------------------------------------------------------------
LAWS = [
    "中华人民共和国劳动法",
    "中华人民共和国劳动合同法",
    "中华人民共和国就业促进法",
    "中华人民共和国劳动争议调解仲裁法",
    "中华人民共和国社会保险法",
    "中华人民共和国工会法",
    "中华人民共和国安全生产法",
    "中华人民共和国职业病防治法",
    "中华人民共和国妇女权益保障法",
    "中华人民共和国残疾人保障法",
    "中华人民共和国未成年人保护法",
    "中华人民共和国矿山安全法",
    "中华人民共和国特种设备安全法",
    "中华人民共和国危险化学品安全法",
    "中华人民共和国医疗保障法",
    "中华人民共和国职业教育法",
    "中华人民共和国人口与计划生育法",
    "中华人民共和国煤炭法",
    "中华人民共和国建筑法",
    "中华人民共和国退役军人保障法",
    "中华人民共和国老年人权益保障法",
    "全国人民代表大会常务委员会关于批准《国务院关于工人退休、退职的暂行办法》的决议",
    "第五届全国人民代表大会常务委员会关于批准《国务院关于职工探亲待遇的规定》的决议",
]

ADMIN = [
    "中华人民共和国劳动合同法实施条例",
    "劳动保障监察条例",
    "工伤保险条例",
    "失业保险条例",
    "社会保险费征缴暂行条例",
    "社会保险经办条例",
    "职工带薪年休假条例",
    "女职工劳动保护特别规定",
    "禁止使用童工规定",
    "使用有毒物品作业场所劳动保护条例",
    "中华人民共和国矿山安全法实施条例",
    "安全生产许可证条例",
    "建设工程安全生产管理条例",
    "煤矿安全生产条例",
    "危险化学品安全管理条例",
    "特种设备安全监察条例",
    "关于工资总额组成的规定",
    "国务院关于职工工作时间的规定",
    "劳动就业服务企业管理规定",
    "国有企业富余职工安置规定",
    "住房公积金管理条例",
    "残疾人就业条例",
    "人力资源市场暂行条例",
    "保障农民工工资支付条例",
    "全国社会保障基金条例",
    "医疗保障基金使用监督管理条例",
    "中华人民共和国尘肺病防治条例",
    "生产安全事故报告和调查处理条例",
    "生产安全事故应急条例",
    "国务院关于预防煤矿生产安全事故的特别规定",
    "国务院关于特大安全事故行政责任追究的规定",
    "煤矿安全监察条例",
    "中华人民共和国劳动保险条例",
    "国务院关于高级专家退休问题的补充规定",
    "国务院关于高级专家离休退休若干问题的暂行规定",
    "国务院关于处理国家机关工作人员退职、退休时计算工作年限的暂行规定",
    "退役军人就业创业促进条例",
    "事业单位人事管理条例",
    "国务院关于安置老弱病残干部的暂行办法",
]

JUDICIAL = [
    "最高人民法院关于审理劳动争议案件适用法律问题的解释（一）",
    "最高人民法院关于审理劳动争议案件适用法律问题的解释（二）",
    "最高人民法院关于审理劳动争议案件适用法律若干问题的解释",
    "最高人民法院关于审理劳动争议案件适用法律若干问题的解释（二）",
    "最高人民法院关于审理劳动争议案件适用法律若干问题的解释（三）",
    "最高人民法院关于审理劳动争议案件适用法律若干问题的解释（四）",
    "最高人民法院关于在民事审判工作中适用《中华人民共和国工会法》若干问题的解释",
    "最高人民法院关于审理工伤保险行政案件若干问题的规定",
    "最高人民法院关于审理拒不支付劳动报酬刑事案件适用法律若干问题的解释",
    "最高人民法院关于人事争议申请仲裁的时效期间如何计算的批复",
    "最高人民法院关于人民法院审理事业单位人事争议案件若干问题的规定",
    "最高人民法院关于解除劳动合同的劳动争议仲裁申请期限应当如何起算问题的批复",
    "最高人民法院关于劳动仲裁委员会逾期不作出仲裁裁决或者作出不予受理通知的劳动争议案件，人民法院应否受理的批复",
    "最高人民法院关于审理劳动争议案件诉讼当事人问题的批复",
    "最高人民法院关于人民法院对经劳动争议仲裁裁决的纠纷准予撤诉或驳回起诉后劳动争议仲裁裁决从何时起生效的解释",
    "最高人民法院关于实行社会保险的企业破产后各种社会保险统筹费用应缴纳至何时问题的批复",
    "最高人民检察院关于挪用失业保险基金和下岗职工基本生活保障资金的行为适用法律问题的批复",
    "最高人民法院、最高人民检察院关于办理危害生产安全刑事案件适用法律若干问题的解释",
]

DECISIONS = [
    "全国人民代表大会常务委员会关于修改《中华人民共和国工会法》的决定",
    "全国人民代表大会常务委员会关于修改《中华人民共和国安全生产法》的决定",
    "全国人民代表大会常务委员会关于修改《中华人民共和国人口与计划生育法》的决定",
    "全国人民代表大会常务委员会关于修改《中华人民共和国农业技术推广法》、《中华人民共和国未成年人保护法》、《中华人民共和国生物安全法》的决定",
    "全国人民代表大会常务委员会关于废止有关劳动教养法律规定的决定",
    "全国人民代表大会常务委员会关于实施渐进式延迟法定退休年龄的决定",
    "全国人民代表大会常务委员会关于授权国务院对职工退休退职办法进行部分修改和补充的决定",
    "全国人民代表大会常务委员会关于授权国务院在河北省邯郸市等十二个试点城市行政区域暂时调整适用《中华人民共和国社会保险法》有关规定的决定（失效）",
    "国务院关于修改《住房公积金管理条例》的决定",
    "国务院关于修改《全国年节及纪念日放假办法》的决定",
    "最高人民法院关于修改《最高人民法院关于在民事审判工作中适用〈中华人民共和国工会法〉若干问题的解释》等二十七件民事类司法解释的决定",
]

GROUPS = {
    "laws": {
        "dir": "data/laws",
        "level": "法律",
        "level_code": 1,
        "codes": [110, 120, 130, 140, 150, 155, 160, 170],
        "titles": LAWS,
    },
    "administrative": {
        "dir": "data/administrative-regulations",
        "level": "行政法规",
        "level_code": 2,
        "codes": [210],
        "titles": ADMIN,
    },
    "judicial": {
        "dir": "data/judicial-interpretations",
        "level": "司法解释",
        "level_code": 3,
        "codes": [320, 330, 340],
        "titles": JUDICIAL,
    },
    "decisions": {
        "dir": "data/decisions",
        "level": "修改废止决定",
        "level_code": 6,
        "codes": [190, 200, 215, 350],
        "titles": DECISIONS,
    },
}

CATEGORY_BY_CODE = {
    110: "宪法相关法", 120: "民法商法", 130: "行政法", 140: "经济法",
    150: "社会法", 155: "生态环境法", 160: "刑法", 170: "诉讼与非诉讼程序法",
}

TOPIC_RULES = [
    (("劳动法",), ["劳动基准", "劳动合同"]),
    (("劳动合同",), ["劳动合同"]),
    (("就业促进", "劳动就业", "人力资源市场", "就业服务", "残疾人就业", "退役军人就业"), ["就业促进"]),
    (("劳动争议", "人事争议", "仲裁办案", "仲裁组织", "工会法"), ["劳动争议处理", "集体合同与工会"]),
    (("社会保险", "工伤保险", "失业保险", "社会保障基金", "医疗保障基金", "劳动保险"), ["社会保险"]),
    (("工会法", "集体合同"), ["集体合同与工会"]),
    (("安全生产", "职业病", "尘肺", "矿山安全", "特种设备", "危险化学品", "有毒物品", "生产安全事故", "煤矿"), ["劳动安全卫生"]),
    (("妇女权益", "女职工", "童工", "未成年工", "人口与计划生育"), ["特殊群体保护"]),
    (("工资", "最低工资", "工作时间", "带薪年休假", "探亲", "农民工"), ["劳动基准", "工资保障"]),
    (("劳动保障监察", "劳动监察", "劳动保护"), ["劳动保障监察"]),
    (("职业教育", "职业技能", "职业培训"), ["职业培训"]),
    (("退休", "退职", "离休"), ["社会保险"]),
    (("事业单位", "人事"), ["人事关系"]),
]

SHORT_OVERRIDE = {
    "中华人民共和国劳动法": "劳动法",
    "中华人民共和国劳动合同法": "劳动合同法",
    "中华人民共和国就业促进法": "就业促进法",
    "中华人民共和国劳动争议调解仲裁法": "劳动争议调解仲裁法",
    "中华人民共和国社会保险法": "社会保险法",
    "中华人民共和国工会法": "工会法",
    "中华人民共和国安全生产法": "安全生产法",
    "中华人民共和国职业病防治法": "职业病防治法",
    "中华人民共和国妇女权益保障法": "妇女权益保障法",
    "中华人民共和国残疾人保障法": "残疾人保障法",
    "中华人民共和国未成年人保护法": "未成年人保护法",
    "中华人民共和国矿山安全法": "矿山安全法",
    "中华人民共和国特种设备安全法": "特种设备安全法",
    "中华人民共和国危险化学品安全法": "危险化学品安全法",
    "中华人民共和国医疗保障法": "医疗保障法",
    "中华人民共和国职业教育法": "职业教育法",
    "中华人民共和国人口与计划生育法": "人口与计划生育法",
    "中华人民共和国煤炭法": "煤炭法",
    "中华人民共和国建筑法": "建筑法",
    "中华人民共和国退役军人保障法": "退役军人保障法",
}


def short_title(title: str) -> str:
    if title in SHORT_OVERRIDE:
        return SHORT_OVERRIDE[title]
    t = title
    for pre in ("中华人民共和国", "最高人民法院关于", "最高人民检察院关于",
                "最高人民法院、最高人民检察院关于", "国务院关于"):
        if t.startswith(pre):
            t = t[len(pre):]
            break
    t = t.replace("《", "").replace("》", "")
    return t[:60]


def topics_for(title: str) -> list[str]:
    topics: list[str] = []
    for keys, vals in TOPIC_RULES:
        if any(k in title for k in keys):
            for v in vals:
                if v not in topics:
                    topics.append(v)
    if not topics:
        topics = ["综合/其他"]
    return topics


def safe_name(title: str, year: str) -> str:
    t = re.sub(r'[\\/:*?"<>|]', "／", title)
    t = re.sub(r"\s+", "", t)
    return f"{t}-{year}"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
def cached_json(path: Path, producer, refresh: bool = False):
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    data = producer()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def enumerate_group(client: FlkClient, key: str, group: dict, refresh: bool) -> list[dict]:
    cache = CACHE / f"list_{key}.json"
    return cached_json(
        cache,
        lambda: client.list_all(codes=group["codes"], size=100),
        refresh,
    )


def tree_article_count(node: dict) -> int:
    n = 0
    title = (node.get("title") or "").strip()
    if re.match(r"^第[一二三四五六七八九十百千零〇两]+条", title):
        n += 1
    for child in node.get("children") or []:
        n += tree_article_count(child)
    return n


def to_markdown(docx: Path, title: str) -> str:
    """pandoc directly, with a LibreOffice fallback for files that are really .doc."""
    try:
        return convert_docx(docx, title=title)
    except Exception as first_err:
        tmp = Path(tempfile.mkdtemp(prefix="labor-doc-"))
        try:
            legacy = tmp / (docx.stem + ".doc")
            shutil.copyfile(docx, legacy)
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "docx", "--outdir", str(tmp), str(legacy)],
                check=True, capture_output=True, timeout=180,
            )
            converted = tmp / (docx.stem + ".docx")
            if not converted.exists():
                raise RuntimeError(f"libreoffice did not produce {converted}") from first_err
            return convert_docx(converted, title=title)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def build_doc(client: FlkClient, row: dict, group: dict, raw_dir: Path,
              refresh: bool = False) -> dict:
    bbbs = row["bbbs"]
    detail = cached_json(CACHE / "detail" / f"{bbbs}.json",
                         lambda: client.detail(bbbs), refresh)
    title = detail.get("title") or clean_title(row["title"])
    level = group["level"]
    promulgated = row.get("gbrq") or detail.get("gbrq") or detail.get("sxrq") or ""
    effective = row.get("sxrq") or detail.get("sxrq") or promulgated
    year = promulgated[:4] if len(promulgated) >= 4 else "无日期"
    slug = safe_name(title, year)

    docx = raw_dir / f"{bbbs}.docx"
    if not docx.exists() or refresh:
        client.download(bbbs, docx, fmt="docx")

    md_body = to_markdown(docx, title=title)
    articles = extract_articles(md_body)
    tree_count = tree_article_count(detail.get("content") or {})

    sxx = row.get("sxx")
    status = SXX.get(sxx, "有效" if group["level"] == "修改废止决定" else "")
    status_code = sxx if sxx is not None else (3 if group["level"] == "修改废止决定" else None)
    fm = {
        "id": f"flk-{bbbs}",
        "title": title,
        "short_title": short_title(title),
        "level": level,
        "level_code": group["level_code"],
        "issuer": detail.get("zdjgName") or "",
        "doc_number": "",
        "promulgated": promulgated,
        "effective": effective,
        "status": status,
        "status_code": status_code,
        "category": CATEGORY_BY_CODE.get(row.get("flfgCodeId"), level),
        "doc_type": level,
        "province": "",
        "topics": topics_for(title),
        "source": f"https://flk.npc.gov.cn/detail?id={bbbs}",
        "source_name": "国家法律法规数据库",
        "retrieved": RETRIEVED,
        "sha256": sha256(md_body),
        "chars": len(re.sub(r"\s", "", md_body)),
        "articles": len(articles),
        "version_group": title,
        "version_note": f"{promulgated or '日期不详'} 公布（{status}）",
        "related": [],
        "notes": "",
    }
    out = ROOT / group["dir"] / f"{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + md_body
    out.write_text(text, encoding="utf-8")

    rec = {
        "id": fm["id"], "bbbs": bbbs, "title": title, "level": level,
        "promulgated": fm["promulgated"], "effective": fm["effective"],
        "status": fm["status"], "path": str(out.relative_to(ROOT)),
        "articles_parsed": len(articles), "articles_in_official_tree": tree_count,
        "chars": fm["chars"], "sha256": fm["sha256"],
        "topics": fm["topics"], "issuer": fm["issuer"],
        "docx": str(docx.relative_to(ROOT)),
    }
    warn = ""
    if tree_count and abs(len(articles) - tree_count) > 2:
        warn = f"article count mismatch: parsed={len(articles)} tree={tree_count}"
        print(f"  ! {title}: {warn}")
    if warn:
        rec["warning"] = warn
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="only show selection matches")
    ap.add_argument("--only", choices=list(GROUPS) + ["decisions"])
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    client = FlkClient(min_interval=1.2, verbose=True)
    records: list[dict] = []
    failures: list[dict] = []

    for key, group in GROUPS.items():
        if args.only and args.only != key:
            continue
        print(f"\n== {key} ({group['level']})")
        rows = enumerate_group(client, key, group, args.refresh)
        by_title: dict[str, list[dict]] = {}
        for row in rows:
            by_title.setdefault(clean_title(row["title"]), []).append(row)
        wanted = set(group["titles"])
        missing = sorted(wanted - set(by_title))
        matched = [t for t in group["titles"] if t in by_title]
        print(f"   rows={len(rows)} titles_selected={len(matched)} missing={len(missing)}")
        for m in missing:
            print(f"   - MISSING: {m}")
        if args.list:
            for t in matched:
                for r in by_title[t]:
                    print(f"   [{r['sxx']}] {r['gbrq']} {t}")
            continue
        for t in matched:
            for row in sorted(by_title[t], key=lambda r: r.get("gbrq") or ""):
                if args.limit and len(records) >= args.limit:
                    break
                try:
                    rec = build_doc(client, row, group, ROOT / "raw" / "flk", args.refresh)
                    records.append(rec)
                    print(f"   ok [{row['sxx']}] {row['gbrq']} {rec['title']} "
                          f"({rec['articles_parsed']} 条)")
                except Exception as e:  # keep going, report at the end
                    failures.append({"bbbs": row["bbbs"], "title": t, "error": str(e)})
                    print(f"   !! FAIL {t} {row['bbbs']}: {e}")
                time.sleep(0.3)

    if not args.list:
        (ROOT / "data" / "manifest.json").write_text(
            json.dumps({
                "generated": RETRIEVED,
                "source": "国家法律法规数据库 https://flk.npc.gov.cn",
                "count": len(records),
                "records": records,
                "failures": failures,
            }, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\nwrote {len(records)} documents, {len(failures)} failures")


if __name__ == "__main__":
    main()
