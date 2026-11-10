#!/usr/bin/env python3
"""由 items.json（flk 核验过的国家层面条目）+ _mohrss_rules.py（人社部规章库全量）
生成 research/coverage/checklist.md。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from _mohrss_rules import BASE as MOHRSS_BASE, RULES

HERE = Path(__file__).resolve().parent
D = json.loads((HERE / "items.json").read_text())
ITEMS = D["items"]

STATUS_ORDER = {"有效": 0, "尚未生效": 1, "已修改": 2, "已废止": 3}


def link(item: dict) -> str:
    if item.get("bbbs"):
        u = "https://flk.npc.gov.cn/detail?title=" + quote(item["title"]) + "&bbbs=" + item["bbbs"]
        return f"[flk]({u})"
    return f"[官方]({item['source_url']})"


def table(items: list[dict], with_topic: bool = True) -> str:
    rows = [
        "| # | 标题 | 制定机关 | 公布日期 | 施行日期 | 时效性 | 现行有效 | flk bbbs | 来源 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, it in enumerate(sorted(items, key=lambda x: (STATUS_ORDER.get(x["status"], 9), x["promulgated"])), 1):
        note = f"<br/>注：{it['note']}" if it.get("note") else ""
        bb = f"`{it['bbbs']}`" if it.get("bbbs") else "—（flk 未收录）"
        rows.append(
            f"| {i} | {it['title']}{note} | {it['issuer']} | {it['promulgated'] or '—'} | "
            f"{it['effective'] or '—'} | {it['status']} | {it['current']} | {bb} | {link(it)} |"
        )
    return "\n".join(rows)


def dept_table() -> str:
    rows = [
        "| # | 标题 | 制定机关 | 文号 | 公布日期 | 施行日期 | 状态 | 核心主题 | 备注 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for no, title, issuer, doc_no, prom, eff, core, note in RULES:
        rows.append(
            f"| {no} | {title} | {issuer} | {doc_no} | {prom} | {eff or '自公布之日'} | 有效 | "
            f"{'★核心' if core else '相关'} | {note} |"
        )
    return "\n".join(rows)


def counts(items: list[dict]) -> dict:
    return {
        "total": len(items),
        "law": sum(1 for i in items if i["category"] == "法律"),
        "admin": sum(1 for i in items if i["category"] == "行政法规"),
        "jud": sum(1 for i in items if i["category"] == "司法解释"),
        "required": sum(1 for i in items if i["required"]),
        "status": dict(Counter(i["status"] for i in items)),
    }


def main() -> None:
    c = counts(ITEMS)
    req = [i for i in ITEMS if i["required"]]
    ext = [i for i in ITEMS if not i["required"]]
    laws, admins, juds = (
        [i for i in ITEMS if i["category"] == "法律"],
        [i for i in ITEMS if i["category"] == "行政法规"],
        [i for i in ITEMS if i["category"] == "司法解释"],
    )
    dept_core = [r for r in RULES if r[6]]
    dept_other = [r for r in RULES if not r[6]]
    hist = D["historical"]

    md = f"""# 劳动法领域 国家级法规全量清单（Coverage Checklist）

- 审计产品：`/root/labor-law-cn` 数据仓库的**覆盖度基线**
- 生成日期：2026-11-10
- 审计人：coverage-auditor（独立审计，未参与数据抓取）
- 核验主源：[国家法律法规数据库 flk.npc.gov.cn](https://flk.npc.gov.cn/)（法律/行政法规/司法解释/修改废止决定）
- 核验副源：[人力资源和社会保障部规章库]({MOHRSS_BASE})（部门规章，flk 不收录该层级）
- 辅助核验：中国政府网 gov.cn 政策文件页（用于 flk 未收录的两部行政法规本体）

## 0. 方法与口径

1. **枚举而非抽样**：直接分页拉取 flk 列表接口中「法律」「行政法规」「司法解释」「有关法律问题的决定」全部条目
   （法律 478 条、行政法规 835 条、司法解释 859 条、决定 188 条），再用劳动法领域关键词过滤，逐条人工确认归属；
   部门规章则逐页抓取人社部规章库现行清单（共 6 页、76 条记录）。
2. **元数据以 flk 列表字段为准**：`gbrq`=公布日期、`sxrq`=施行日期、`sxx`=时效性（1 已废止/2 已修改/3 有效/4 尚未生效）、
   `zdjgName`=制定机关、`bbbs`=版本标识。flk 列表 `sxrq` 为空的，用 flk 详情接口的 `sxrq` 或官方公布信息补全并加注。
3. **现行有效判定**：`status_code=3/4` 且为最新版本 → 现行有效（4 表示尚未生效）；`status_code=1` → 已废止；
   `status_code=2` → 已被修改（同 `version_group` 另有现行版本）。
4. **flk 未收录层级**：部门规章不在国家法律法规数据库中；《国务院关于工人退休、退职的暂行办法》
   《国务院关于职工探亲待遇的规定》两部行政法规本体 flk 仅收录全国人大批准决议，本体需从 gov.cn 取得。
5. **规模**：本清单共 {c['total']} 项国家层面文件（法律 {c['law']}、行政法规 {c['admin']}、司法解释 {c['jud']}；
   另部门规章 {len(RULES)} 条记录）——其中任务要求的**必选核心项 {c['required']} 项**，扩展建议项 {len(ext)} 项。

> 说明：清单把「与劳动法领域强相关」的上位/背景法（建筑法、煤炭法、职业教育法、退役军人保障法、公司法、企业破产法、
> 公务员法、军人保险法、仲裁法、基本医疗卫生与健康促进法、人口与计划生育法、预防未成年人犯罪法）列为**扩展项**，
> 不作为必选；理由见每项备注。是否纳入仓库由项目 owner 决定。

## 1. 法律（全国人大及其常委会）

{table(laws)}

## 2. 行政法规（国务院）

{table(admins)}

## 3. 司法解释（最高法/最高检）

{table(juds)}

## 4. 部门规章（人力资源和社会保障部规章库现行有效清单，flk 不收录）

来源：{MOHRSS_BASE}（分页 `index.html`、`index_1.html`…`index_5.html`，2026-11-10 抓取）。
全部 {len(RULES)} 条记录中，标注「★核心」的 {len(dept_core)} 条直接对应劳动基准/劳动合同/社保/争议处理/监察/特殊群体保护；
标注「相关」的 {len(dept_other)} 条为人事管理、职称、人才服务、职业培训等外围主题。

{dept_table()}

> 注：第 76 条与第 75 条标题、文号完全相同，系人社部规章库列表的重复收录（非仓库问题，但提示：以该库为依据抓取时需去重）。

### 4.1 已从人社部规章库现行清单消失、需确认状态的历史规章

以下 2 部曾长期有效，本次抓取的现行清单中已不存在（推断已废止或被新规章取代），**不应作为"有效"入库**：

| 规章 | 原文号 | 原公布/施行 | 推断状态 | 证据 |
|---|---|---|---|---|
| 社会保险费申报缴纳管理规定 | 人社部令第20号 | 2013-09-26 / 2013-11-01 | 已废止（待官方废止决定核验） | 人社部规章库现行 76 条中无此条 |
| 工伤职工劳动能力鉴定管理办法 | 人社部令第21号 | 2014-02-20 / 2014-04-01 | 已被《劳动能力鉴定管理办法》（令第55号，2025-07-01）取代 | 规章库第 2 条；旧办法不再单列 |

## 5. 必须指出的覆盖边界（写 gap-report 时按此判定）

1. **flk 详情接口的目录树（`content`）只对部分"法律"存在**：本次抽查 20 部法律中，
   《危险化学品安全法》《医疗保障法》《仲裁法》（均为 2025 年后新法）及两份人大决议的 `content` 为 `null`；
   **全部行政法规、全部司法解释的 `content` 均为 `null`**（实测《工伤保险条例》detail 响应仅 575 字节且 content=null）。
   因此"对照 flk 目录树核对条文数"只能对约 2/3 的法律执行；行政法规/司法解释必须改用 docx 正文自身校验。
2. **flk 列表 `sxrq` 大量为空**（行政法规尤其明显），仓库 `effective` 字段若直接取列表值会大面积缺日期；
   本清单对可确证的条目补注了官方施行日，并注明补注依据。
3. **两部行政法规本体 flk 未收录**（仅收批准决议），仓库若只从 flk 抓取，必然缺失其正文。
4. **部门规章 flk 完全不收录**，必须走人社部官网/国家规章库；且人社部规章库存在 1 条重复记录。

## 6. 历史版本/已废止条目（仅备查，不要求入库）

以下条目在 flk 中有独立 `bbbs`，是同一法规的历史版本或已废止文件，用于 `version_group` 沿革校验：

| # | 标题/说明 | flk bbbs |
|---|---|---|
"""
    for i, h in enumerate(hist, 1):
        md += f"| {i} | {h['note']} | `{h['bbbs']}` |\n"
    md += f"""
## 7. 与 data/ 目录的比对结果

见 `research/coverage/gap-report.md`（阶段 B 产物）。
"""
    (HERE / "checklist.md").write_text(md)
    print("wrote checklist.md", len(md), "chars")


if __name__ == "__main__":
    main()
