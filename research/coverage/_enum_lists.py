#!/usr/bin/env python3
"""枚举 flk 国家法律法规数据库中与劳动法领域相关的全部条目（列表页数据）。

列表接口 POST /law-search/search/list 在无 WAF 拦截的情况下可直接访问。
结果缓存到 research/coverage/cache/ 下，避免重复请求。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from flk_client import FlkClient, clean_title  # noqa: E402

CACHE = ROOT / "research/coverage/cache"
CACHE.mkdir(parents=True, exist_ok=True)

LAW_CODES = [110, 120, 130, 140, 150, 155, 160, 170]
CATS = {
    "laws": LAW_CODES,
    "admin_regs": [210],
    "judicial": [320, 330, 340],
    "law_interpretations": [180],
    "decisions": [190],
    "local": [230],
}

KEYWORDS = [
    "劳动", "劳资", "用工", "就业", "失业", "社会保险", "社保", "养老", "医疗",
    "工伤", "生育", "住房公积金", "工资", "薪酬", "工时", "休假", "退休", "退职",
    "探亲", "工会", "职工", "工人", "农民工", "安全生产", "职业病", "矿山安全",
    "特种设备", "危险化学品", "生产安全", "煤矿", "童工", "女职工", "妇女权益",
    "残疾人", "未成年人", "集体合同", "劳务派遣", "劳动争议", "人事争议", "仲裁",
    "劳动保障监察", "劳动保护", "职业培训", "人力资源市场", "社会保障基金",
    "医疗保障", "基本医疗卫生", "人口与计划生育", "军人保险", "船员", "海员",
    "企业破产", "公司法", "劳动合同", "劳动教养", "劳动改造", "劳动保险",
    "企业职工", "机关事业单位", "事业单位", "公务员", "工伤认定", "事故报告",
]


def fetch(cat: str, codes: list[int]) -> list[dict]:
    f = CACHE / f"list_{cat}.json"
    if f.exists():
        return json.loads(f.read_text())
    cli = FlkClient(min_interval=0.5)
    rows = cli.list_all(codes=codes, size=100)
    for r in rows:
        r["title"] = clean_title(r.get("title"))
    f.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"{cat}: {len(rows)} rows", flush=True)
    return rows


def main() -> None:
    allrows: dict[str, list] = {}
    for cat, codes in CATS.items():
        if cat == "local":
            continue
        allrows[cat] = fetch(cat, codes)
    pool = []
    for cat, rows in allrows.items():
        for r in rows:
            if any(k in r["title"] for k in KEYWORDS):
                pool.append({**r, "cat": cat})
    pool.sort(key=lambda r: (r["cat"], r["title"]))
    (CACHE / "pool.json").write_text(json.dumps(pool, ensure_ascii=False, indent=1))
    print(f"pool: {len(pool)}")
    for r in pool:
        print(f'{r["cat"]:10s} {r["sxx"]} {r["gbrq"]} {r["sxrq"]} {r["bbbs"]} {r["title"]} | {r["zdjgName"]} | {r["flfgCodeId"]}')


if __name__ == "__main__":
    main()
