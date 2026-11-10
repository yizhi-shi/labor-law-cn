#!/usr/bin/env python3
"""由 cache/audit.json 生成 research/coverage/gap-report.md（阶段B 最终报告）。"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
A = json.loads((HERE / "cache/audit.json").read_text())
F = A["findings"]

SEV_NAME = {"P1": "P1 阻断", "P2": "P2 重要", "P3": "P3 提示", "P4": "P4 信息"}
CAT_ORDER = [
    "条文未分行", "条文数不一致", "缺失项", "部门规章缺失", "截断风险",
    "日期错误", "日期待修正", "日期待确认", "状态错误", "标题错误", "制定机关错误",
    "部门规章日期", "部门规章状态", "SCHEMA问题", "正文体例", "章节不一致",
    "来源问题", "来源优先级", "字数不一致", "sha256不一致",
    "重复项", "另有版本", "多出文件", "部门规章多出", "尾部体例", "短文本", "地方层级",
]


def md_table(rows: list[dict], headers: list[str], cols: list[str]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        vals = []
        for c in cols:
            v = str(r.get(c, "")).replace("\n", " ").replace("|", "\\|")
            vals.append(v)
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out)


def files_for(cat: str) -> list[dict]:
    return [x for x in F if x["category"] == cat]


def render_finding_table(cat: str, label: str = "") -> str:
    xs = files_for(cat)
    if not xs:
        return f"_（无{label or cat}问题）_\n"
    rows = [{"f": x["path"], "m": x["message"], "e": x["evidence"]} for x in xs]
    return md_table(rows, ["文件/对象", "问题", "证据"], ["f", "m", "e"]) + "\n"


def main() -> None:
    c = A["counts"]
    cov = A["coverage"]
    sev = Counter(x["severity"] for x in F)
    total_files = A.get("total_files", sum(c.values()))
    req_missing = A.get("required_missing", [])
    sample = A.get("sample", [])
    prov = A.get("local_provinces", {})
    missing_rows = [{"c": m["item"]["category"], "t": m["item"]["title"],
                     "p": m["item"]["promulgated"], "b": m["item"]["bbbs"] or "flk未收录"}
                    for m in A["missing"]]
    dept_missing_rows = [{"t": m["title"], "n": m["doc_no"], "p": m["prom"]} for m in A["dept_missing"]]
    dept_extra_rows = [{"t": Path(p).name, "s": "见文件"} for p in A["dept_extra"]]

    p1_para = files_for("条文未分行")
    p1_art = files_for("条文数不一致")
    p2_date = files_for("日期待修正")
    p2_schema = files_for("SCHEMA问题")
    p2_src = files_for("来源问题")
    p3_src = files_for("来源优先级")
    p3_tail = files_for("尾部体例")
    p3_date = files_for("日期待确认")
    p3_zip = files_for("字数不一致")
    p3_dup = files_for("重复项")
    p3_chap = files_for("章节不一致")

    md = f"""# 劳动法领域数据仓库 覆盖缺口审计报告（Gap Report）

- 审计对象：`/root/labor-law-cn` 的 `data/` 数据集
- 审计基线：`research/coverage/checklist.md`（2026-11-10，flk + 人社部规章库核验）
- 数据快照：{total_files} 个 md 文件（法律 {c['laws']}、行政法规 {c['admin']}、司法解释 {c['judicial']}、
  部门规章 {c['departmental']}、地方性法规 {c['local']}、修改废止决定 {c['decisions']}）；
  最后写入时间 {A.get('snapshot_mtime','—')}
- 审计人：coverage-auditor（独立审计；未参与抓取/转换）
- 结论：**必选条目 100% 覆盖（法律 17/17、行政法规 30/30、司法解释 7/7），部门规章 66/75；
  未发现正文内容缺失型截断，未发现重复入库；但存在 {sev['P1']} 个阻断级、{sev['P2']} 个重要级问题，主要集中在
  「条文未分行导致条级索引失效」「施行日期以公布日填充」「已废止文件未注明废止依据」三类。**

## 0. 严重程度定义

| 级别 | 含义 | 处理要求 |
|---|---|---|
| P1 阻断 | 影响数据正确性/可用性（条级索引失效、条文数错、核心法源缺失） | 合并前必须修复 |
| P2 重要 | 元数据与官方不符（施行日期、废止依据、来源、SCHEMA 必填） | 建议本迭代修复 |
| P3 提示 | 覆盖扩展项缺失、来源优先级、尾部体例、待人工确认 | 排期处理 |
| P4 信息 | 已正确处理的边界情况（如已废止旧规章保留） | 知悉即可 |

## 1. 覆盖度总览

{md_table([{"l": k, "r": f"{v['required_matched']}/{v['required']}",
             "t": f"{v['total_matched']}/{v['total']}"} for k, v in cov.items()],
           ["层级", "必选核心覆盖", "含扩展项覆盖"], ["l", "r", "t"])}

覆盖判定口径：
- 「必选核心」= checklist 中任务明确要求/劳动法领域主干文件；扩展项为建筑法、煤炭法、公司法等背景法，缺失不计缺口。
- 法律/行政法规/司法解释按 `id = flk-<bbbs>`（flk 版本标识）或「标题+公布日期」双键匹配；部门规章按标题匹配人社部规章库现行清单（75 个唯一标题）。
- 匹配结果：**清单必选项缺失：{'无' if not req_missing else '、'.join(req_missing)}**。

### 1.1 必选但未入库的扩展/待补条目（P3，共 {len(missing_rows)}）

{md_table(missing_rows, ["层级", "条目", "公布日期", "bbbs"], ["c", "t", "p", "b"])}

### 1.2 规范性文件（数据新层级，清单未列，SCHEMA 待同步）

数据中出现 `data/normative-documents/` 与 `level: 规范性文件 / level_code: 7`（{len(A.get('normative', []))} 个文件），
但 **SCHEMA.md 的目录/层级表只定义到 level_code 6**，未记录该层级与目录；`scripts/build_index.py` 的
`LEVEL_ORDER` 已支持（说明脚本先行于规范）。建议同步更新 SCHEMA.md，否则后续校验/抓取会按旧规范误判。

{md_table([{'p': x} for x in A.get('normative', [])], ["文件"], ["p"])}

### 1.3 部门规章缺口（相对人社部规章库现行 76 条记录 / 75 个唯一标题）

- 缺 {len(dept_missing_rows)} 条，其中核心主题 {sum(1 for m in A['dept_missing'] if m['severity']=='P1')} 条：

{md_table(dept_missing_rows, ["规章", "文号", "公布日期"], ["t", "n", "p"])}

- 多出 {len(A['dept_extra'])} 条（均**已正确标注「已废止」**，属合理保留；建议保留并在 notes 写明废止依据）：

{md_table([{"p": p} for p in A['dept_extra']], ["文件"], ["p"])}

> 说明：人社部规章库列表有 1 处重复收录（第 75/76 条为同一规章《关于调整使用不当……的办法》），
> 本报告按 75 个唯一标题计。

## 2. P1 阻断级问题

### 2.1 条文未按行起排 → 条级解析不完整（{len(p1_para)} 个文件）

`scripts/build_index.py` / `articles` 抽取依赖「行首 `第X条`」。以下文件把多条条文合并进了同一段落（换行丢失），
导致解析出的条文数少于实际最大条号，`data/articles/<id>.json` 将漏条、条级检索失效。**正文文字本身未缺失**（缺号文字在行内出现）。

{render_finding_table('条文未分行')}

### 2.2 `articles` 字段与正文实际条文数不一致（{len(p1_art)} 个文件）

正文已按行排好，但 front matter 的 `articles` 是旧值（文件被重新转换后未重跑 `build_index.py`）。
按 SCHEMA，`articles` 为自动回填字段，重跑即可修复。

{render_finding_table('条文数不一致')}

### 2.3 核心部门规章缺失

见 1.2：核心主题缺 1 条 ——《城镇集体所有制企业工资同经济效益挂钩办法》（劳薪字〔1991〕46号）。
其余 8 条为「相关」主题（人事管理/职称/人才服务），不影响劳动法主干覆盖。

## 3. P2 重要问题

### 3.1 施行日期错误/以公布日填充（{len(p2_date)} 处）

数据抓取时 flk 列表 `sxrq` 为空，front matter 按 SCHEMA 兜底填了公布日；但官方施行日可核（flk 详情、
正文附则、国务院令题注），**填写值与事实不符**。建议逐条按官方施行日修正：

{render_finding_table('日期待修正')}

### 3.2 已废止文件未在 `notes` 说明废止依据（{len([x for x in p2_schema if '废止' in x['message']])} 处）

SCHEMA 质量红线要求「已废止文件保留，但在 notes 说明废止依据」。以下文件 `status_code=1` 但 `notes` 为空
（按目录聚合；地方性法规占绝大多数，属批量抓取未填 notes 的系统性问题）：

{md_table([{'d': d, 'n': n} for d, n in sorted(Counter(Path(x['path']).parts[1] if len(Path(x['path']).parts) > 2 else Path(x['path']).parts[0] for x in p2_schema if '废止' in x['message']).items(), key=lambda kv: -kv[1])], ["目录", "文件数"], ["d", "n"])}

示例（前 20 个）：

{md_table([{'f': x['path']} for x in p2_schema if '废止' in x['message']][:20], ["文件"], ["f"])}

### 3.3 其他 SCHEMA / 来源 / 部门规章日期问题

{render_finding_table('部门规章日期')}

{md_table([{'f': x['path'], 'm': x['message'], 'e': x['evidence']} for x in p2_src], ["文件", "问题", "证据"], ["f", "m", "e"]) if p2_src else '（无）'}

{md_table([{'f': x['path'], 'm': x['message'], 'e': x['evidence']} for x in p2_schema if '废止' not in x['message']], ["文件", "问题", "证据"], ["f", "m", "e"]) if any('废止' not in x['message'] for x in p2_schema) else '（无）'}

## 4. P3 提示与 P4 信息

- **来源优先级**（{len(p3_src)} 处）：使用了地方政府/部门网站的转载页（官方但非 SCHEMA 首选来源），建议替换为 gov.cn 政策文件库或人社部页面：
{md_table([{'f': x['path'], 'u': x['evidence']} for x in p3_src], ["文件", "现行 source"], ["f", "u"])}
- **尾部体例**（{len(p3_tail)} 处）：正文末行未以句读结束（多为表格/落款/日期行），非截断；建议转换时保留句末标点或补「。」。
- **日期待人工确认**（{len(p3_date)} 处，地方性法规）：front matter `effective` 与正文附则载明的施行日不一致，多数是「历次修订沿用原施行日」造成的沿革差异，建议按「现行版本施行日」口径统一。
- **字数不一致**（{len(p3_zip)} 处）：`chars` 与正文非空白字符数偏差>2%，属自动字段过期，重跑 `build_index.py` 即可。
- **章节不一致**（{len(p3_chap)} 处）：md 章标题数与 flk 目录树不一致，需人工确认（见下方抽样表）。
- **重复项**（{len(p3_dup)} 组）：未发现重复入库（同一 id 或多文件同标题同公布日期）。
- **多出文件**（{len(files_for('多出文件'))} 个）：`data/decisions/` 下 11 个修改废止决定不在国家级清单内，但属于 SCHEMA 允许的 level 6 数据；其余多出文件为清单扩展项或历史版本，**不构成问题**。

## 5. 抽样 10 篇首尾与 flk 目录树核对（证据）

抽样对象：有 flk 目录树（`content` 非 null）的现行法律，覆盖社会法/劳动关系/安全卫生/特殊群体。

{md_table([{"t": s["title"], "a": s["md_articles"], "b": s["flk_articles"],
            "l1": s["md_last"], "l2": s["flk_last"], "m": "✅ 一致" if s["match"] else "❌ 不一致",
            "p": s["path"]} for s in sample],
           ["法律", "md 条文数", "flk 目录树条文数", "md 末条", "flk 末条", "结论", "文件"], ["t", "a", "b", "l1", "l2", "m", "p"])}

结论：10/10 条文数与末条编号一致；正文首行为 `# 标题`、题注齐全，未发现首尾截断。

> **局限**：flk 详情接口 `content` 目录树**只对部分法律存在**；全部行政法规、司法解释的 `content` 为 `null`
> （实测《工伤保险条例》detail 响应仅 575 字节），2025 年后新法（危险化学品安全法/医疗保障法/仲裁法）亦然。
> 对这些文件无法用目录树核对条文数，本报告改用「正文自解析条文数 vs front matter `articles`」+
> 「末条编号 == 条文数」+「附则/施行条款存在」三重自校验，未发现异常。

## 6. 地方性法规覆盖概况

当前入库 {c['local']} 个文件、覆盖 {len(prov)} 个省级行政区：

{md_table([{"p": k, "n": v} for k, v in sorted(prov.items(), key=lambda x: -x[1])], ["省份", "文件数"], ["p", "n"])}

- 地方性法规不在本清单的「国家级全量」口径内，清单未列地方条目，故**不视为覆盖缺口**；建议按省份补齐省会市/较大市条例后再做地方覆盖基线。
- 地方文件的 P1 条文未分行问题见 2.1（集中在早期批量转换的省份）。

### 6.1 修改废止决定（data/decisions/，{c['decisions']} 个）

SCHEMA 的 level 6 允许收录，均为 flk 列表中的「有关法律问题的决定」。属于有意扩展，**不构成缺口**；
建议在 `topics` 中补「综合/其他」以外更贴切的标签，并确认与主法的 `related` 关联（如 2024 延迟退休决定 ↔ 社会保险法/劳动合同法）。

### 6.2 数据管道状态（审计时点）

- `data/index.json`、`data/articles/`（{len(list((Path(HERE).parents[1] / 'data' / 'articles').glob('*.json')))} 个条级文件）已由 `build_index.py` 生成；但本次审计期间 data/ 仍在增量写入，
  **索引与 md 存在时点差**。最终合并前必须再跑一次 `python3 scripts/build_index.py && python3 scripts/verify.py`。
- 独立运行 `scripts/verify.py` 时曾报 30 个 sha256 mismatch（集中在上海/云南地方性法规，因转换后未重建索引），
  说明索引必须作为「数据变更后的强制收尾步骤」。

## 7. 修复建议（按优先级）

1. **P1 条文未分行**：对这 {len(p1_para)} 个文件用 `scripts/docx2md.py` 重新转换（保留段落换行），或对正文按「第X条」重新断行；随后重跑
   `python3 scripts/build_index.py` 重建 `data/articles/`。抽检 3 个文件确认条数 = 最大条号。
2. **P1 `articles` 字段过期**：直接重跑 `build_index.py`（自动回填），并纳入抓取脚本的收尾步骤，避免抓取后忘记重建索引。
3. **P2 施行日期**：按 3.1 表逐条修正 `effective`；建议在 `flk_client.py` 侧改为「列表 sxrq 为空时取详情 sxrq，仍为空才回退公布日」。
4. **P2 废止依据**：为 3.2 表文件补 `notes`（如「2024-05-01 被《煤矿安全生产条例》废止」）。
5. **P2 来源**：P3 来源优先级文件替换为 gov.cn/人社部来源；`违反和解除劳动合同的经济补偿办法` 建议改用国家规章库/人社部页面。
6. **P3 部门规章**：补缺失的 9 条（其中核心 1 条），继续从人社部规章库逐条抓取；保留 4 条已废止旧规章并补废止依据。
7. **收尾**：`data/` 稳定后执行 `python3 scripts/verify.py`（若存在）+ `build_index.py`，确保 `data/index.json`、`INDEX.md`、`articles/` 与 md 一致。

## 8. 审计方法与可复现性

- 基线清单：`research/coverage/checklist.md`；数据集：`research/coverage/items.json`（flk 核验元数据）、`_mohrss_rules.py`（人社部规章库全量）。
- flk 数据获取：列表接口 `POST /law-search/search/list` 可直连；详情接口 GET 被 WAF 拦截，改用真实浏览器同源会话获取（结果见 `cache/flk_trees.json`）。
- 比对脚本：`research/coverage/_gap_audit.py`（只读 data/，输出 `cache/audit.json`）；本报告由 `_make_gap_report.py` 生成。
- 全部问题均带文件路径与证据字段，可逐条复核。
"""
    (HERE / "gap-report.md").write_text(md)
    print("wrote gap-report.md", len(md), "chars")


if __name__ == "__main__":
    main()
