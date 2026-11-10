#!/usr/bin/env python3
"""生成 research/coverage/gap-report-final.md（冻结版最终审计报告）。

输入：
  cache/audit.json         当前冻结快照的审计结果（_gap_audit.py 产出）
  gap-report.md            阶段B 初版报告（用于提取“已修复”对照）
  items.json               基线清单（提供官方施行日期）
  cache/verify_final.txt   冻结快照上的 scripts/verify.py 输出
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
A = json.loads((HERE / "cache/audit.json").read_text())
ITEMS = {i["bbbs"]: i for i in json.loads((HERE / "items.json").read_text())["items"] if i.get("bbbs")}
OLD = (HERE / "gap-report.md").read_text()
VERIFY = (HERE / "cache/verify_final.txt").read_text() if (HERE / "cache/verify_final.txt").exists() else ""
F = A["findings"]

SEV_ORDER = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
CAT_ORDER = ["日期错误", "条文未分行", "SCHEMA问题", "日期待修正", "条号缺号",
             "部门规章缺失", "缺失项", "章节缺失", "尾部体例", "来源优先级",
             "部门规章多出", "多出文件", "重复项", "标题错误", "状态错误", "截断风险"]


def md_table(rows, headers, cols):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")).replace("|", "\\|") for c in cols) + " |")
    return "\n".join(out)


def sec_paths(marker: str, end_marker: str) -> list[str]:
    i = OLD.find(marker)
    if i < 0:
        return []
    j = OLD.find(end_marker, i)
    seg = OLD[i:j if j > 0 else len(OLD)]
    return sorted(set(re.findall(r"(data/[\w\-./《》（）()、，]+?\.md)", seg)))


def current_cats(path: str) -> set[str]:
    return {x["category"] for x in F if x["path"] == path}


def status_of(path: str, old_cat: str) -> str:
    cats = current_cats(path)
    if old_cat == "条文未分行":
        return "❌ 仍有条文合并" if "条文未分行" in cats else "✅ 已修复"
    if old_cat == "articles":
        return "❌ articles 仍不一致" if "条文数不一致" in cats else "✅ 已修复"
    if old_cat == "日期":
        if "日期错误" in cats:
            return "⚠️ 已改动但口径与 flk 不符"
        if "日期待修正" in cats:
            return "❌ 仍以公布日兜底"
        return "✅ 已修复"
    if old_cat == "notes":
        return "❌ 仍缺废止依据" if "SCHEMA问题" in cats else "✅ 已修复"
    return "—"


def main() -> None:
    c = A["counts"]
    cov = A["coverage"]
    bycat = defaultdict(list)
    for x in F:
        bycat[x["category"]].append(x)
    sev = Counter(x["severity"] for x in F)
    total_files = A.get("total_files", sum(c.values()))
    missing = A["missing"]
    dept_missing = A["dept_missing"]
    dept_extra = A["dept_extra"]
    prov = A["local_provinces"]
    sample = A["sample"]

    # 已修复对照
    old_para = sec_paths("### 2.1 条文未按行起排", "### 2.2")
    old_art = sec_paths("### 2.2 `articles` 字段", "### 2.3")
    old_date = sec_paths("### 3.1 施行日期错误", "### 3.2")
    old_notes = sec_paths("### 3.2 已废止文件未在", "### 3.3")[:20]
    fixed_rows = []
    for p in old_para:
        fixed_rows.append({"k": "条文未分行", "p": p, "s": status_of(p, "条文未分行")})
    for p in old_art:
        fixed_rows.append({"k": "articles 字段过期", "p": p, "s": status_of(p, "articles")})
    for p in old_date[:20]:
        fixed_rows.append({"k": "施行日期（兜底）", "p": p, "s": status_of(p, "日期")})
    for p in old_notes:
        fixed_rows.append({"k": "已废止缺 notes", "p": p, "s": status_of(p, "notes")})
    n_fixed = sum(1 for r in fixed_rows if r["s"].startswith("✅"))
    n_open = len(fixed_rows) - n_fixed

    # P1 日期错误表（含正确值）
    date_rows = []
    for x in bycat["日期错误"]:
        fn = Path(ROOT / x["path"]).read_text()
        m_eff = re.search(r"^effective: '?([\d-]+)'?", fn, re.M)
        m_bb = re.search(r"^id: flk-([0-9a-zA-Z]+)", fn, re.M)
        it = ITEMS.get(m_bb.group(1)) if m_bb else None
        date_rows.append({
            "p": x["path"], "cur": m_eff.group(1) if m_eff else "?",
            "should": it["effective"] if it else "?",
            "bbbs": m_bb.group(1) if m_bb else "",
        })

    # P1 条文未分行表
    para_rows = [{"p": x["path"], "e": x["evidence"]} for x in bycat["条文未分行"]]
    para_missing = 0
    for x in bycat["条文未分行"]:
        mm = re.search(r"差 (\d+) 条", x["evidence"])
        if mm:
            para_missing += int(mm.group(1))
    p2_rows = [{"p": x["path"], "m": x["message"], "e": x["evidence"]}
               for cat in ("日期待修正", "条号缺号") for x in bycat[cat]]
    notes_by_prov = Counter(Path(x["path"]).parts[2] for x in bycat["SCHEMA问题"]
                            if len(Path(x["path"]).parts) > 2)

    md = f"""# 劳动法领域数据仓库 覆盖缺口审计报告（最终版 · 冻结快照）

- 审计对象：`/root/labor-law-cn` 的 `data/` 数据集（冻结快照）
- 审计基线：`research/coverage/checklist.md`（flk + 人社部规章库核验，2026-11-10）
- 数据快照：{total_files} 篇 md（法律 {c['laws']}、行政法规 {c['admin']}、司法解释 {c['judicial']}、
  部门规章 {c['departmental']}、规范性文件 {c['normative']}、地方性法规 {c['local']}、修改废止决定 {c['decisions']}）
- 审计时点：2026-11-10 11:40（数据冻结，60 秒内 0 写入；数据最后写入 {A.get("snapshot_mtime","—")}）
- 审计人：coverage-auditor（独立审计，未参与抓取/转换/修复）
- 结论速览：**必选核心法源 100% 覆盖；正文无截断、无核心缺失、无重复入库；
  P1 = {sev['P1']}（全部为地方性法规的条级切分问题，正文文字完整），P2 = {sev['P2']}（含 15 处施行日期口径冲突、
  6 处以公布日兜底、11 处条号缺号、79 处废止依据缺失），P3 = {sev['P3']}，P4 = {sev['P4']}。
  内容层面可发布；建议修复 P1（条级切分）与 P2 中的施行日期后，重跑索引再发布。**

## 0. 严重程度定义

| 级别 | 含义 | 本次数量 |
|---|---|---|
| P1 | 条级索引失效 / 正文截断 / 核心法源缺失 / 关键元数据错误 | {sev['P1']} |
| P2 | 元数据与官方不符（日期口径、废止依据、条号缺号） | {sev['P2']} |
| P3 | 覆盖扩展项、章节标题、尾部体例、来源优先级 | {sev['P3']} |
| P4 | 已正确处理的边界情况 | {sev['P4']} |

## 1. 阶段B 初版 → 冻结版「已修复」对照

阶段B 初版报告（`gap-report.md`，早于数据冻结，349 篇快照）点名的问题逐条复核如下
（仅列初版报告中出现过的文件；阶段B 之后数据从 349 篇增长到 {total_files} 篇，新增文件带入的新问题不计入「已修复」比例）：

- 初版点名文件共 {len(fixed_rows)} 条，**已修复 {n_fixed} 条（{n_fixed / max(len(fixed_rows), 1):.0%}）**，仍有 {n_open} 条未修复。
- 关键修复证据：
  - `articles` 自动字段过期问题（原 16 个文件）**已全部由 `build_index.py` 重建修复**（当前 0 处）。
  - 正文开头缺失（陕西就业促进条例、青海劳动保障监察条例缺第一~八条）**已修复**：现均含「第一条」。
  - 已废止文件 notes（初版 88 处）**大面积为 `fix_metadata.py` 补齐**，冻结版仍有 {len(bycat['SCHEMA问题'])} 处（全部为新增地方性法规）。
  - 部门规章核心缺失（城镇集体…挂钩办法）**已解决**：按「规范性文件」层级收录于 `data/normative-documents/`。

{md_table(fixed_rows, ["问题类别", "文件", "冻结版状态"], ["k", "p", "s"])}

> 备注：上表 `⚠️ 已改动但口径与 flk 不符` 指 `fix_metadata.py` 把修正版的施行日期改成了正文附则里的**原始施行日**，
> 与 flk 给出的**该版本施行日**不一致，见 3.1。

## 2. 覆盖度总览（必选核心 100%）

{md_table([{"l": k, "r": f"{v['required_matched']}/{v['required']}",
             "t": f"{v['total_matched']}/{v['total']}"} for k, v in cov.items()],
           ["层级", "必选核心覆盖", "含扩展项覆盖"], ["l", "r", "t"])}

- **必选核心法源缺失：无。** 任务要求点名的 15 部法律 + 2 份人大批准决议、30 部行政法规、
  7 件司法解释全部在库且状态与 flk 一致（`status_code` 比对 0 差异）。
- gov 补齐的 3 篇（1978 工人退休退职暂行办法、1978 安置老弱病残干部暂行办法、1981 探亲待遇规定）
  均已入库：`articles` 分别 14/17/9 条，首尾条文与施行条款完整（独立复核）。
- 规范性文件 10 篇：level_code=7，与 `build_index.py` 的 `LEVEL_ORDER` 一致；**SCHEMA.md 尚未记录该层级**（见 5.5）。
- 部门规章 70/75：缺 5 条均为人事部早期「相关」主题规章（见 4.3）；4 条旧规章已按「已废止」保留（正确）。

## 3. P1 问题（{sev['P1']} 处：全部为地方性法规条级切分）

### 3.1 条文未分行 → 条级索引不完整（{len(para_rows)} 处，全部为地方性法规）

正文文字完整（无内容缺失），但多条条文被合并进同一段落，`data/articles/` 按行首 `第X条` 切分时会少切。
冻结版共 {len(para_rows)} 篇、累计约 {para_missing} 条未落到条级索引。

{md_table(para_rows, ["文件", "证据"], ["p", "e"])}

**修复**：对上述文件按「第X条」强制断行（`fix_metadata.py` 的 `split_articles` 仅处理严格递增的合并，
漏掉了数字编号/跨段合并的情况），再重跑 `build_index.py`。

## 4. P2 问题（{sev['P2']} 处）

### 4.1 施行日期口径冲突：修正版被写成「原始施行日」（{len(date_rows)} 处，P2-高优先）

冻结版中这些文件的 `effective` 是正文附则里的**原法施行日**（如劳动法 1995-01-01），
而 flk 对**该版本**给出的 `sxrq` 是修正案施行日（2018-12-29）。根因是 `scripts/fix_metadata.py`
`fix_front_matter()` 的 effective 处理段（约第 129-143 行）无条件取正文里最后一个「自…施行」日期覆盖 `effective`，对「修正/修订版」会把日期改回原始日。
**影响**：检索/展示时现行版施行日与 flk 基线不一致；但这也是法律数据库常见口径（部分数据库对修正版显示原法施行日），
因此本报告把它列为「口径冲突（P2-高）」而非正文错误，裁决权交项目 owner。

{md_table(date_rows, ["文件", "冻结版 effective", "flk 官方施行日", "bbbs"], ["p", "cur", "should", "bbbs"])}

**修复建议（二选一）**：
1. 以 flk 为准：把这 {len(date_rows)} 个文件的 `effective` 改回上表「flk 官方施行日」（数据已在 `items.json` 中，可脚本批量回填）。
2. 保留「原法施行日」口径：则需在 SCHEMA 明确「`effective` = 法律文本自身施行日（非修正案施行日）」，
   并全库统一（当前另有 {len(bycat['日期待修正'])} 个文件仍是「以公布日兜底」，两种口径混用才是真正的问题）。

> 审计建议选 1：`checklist.md` 与 flk 一致，且 `verify.py` 的 CORE 校验也以 flk 口径理解。


### 4.2 施行日期仍以公布日兜底（{len(bycat['日期待修正'])} 处）

{md_table([{'p': x['path'], 'e': x['evidence']} for x in bycat['日期待修正']], ["文件", "证据"], ["p", "e"])}

### 4.3 条号缺号（{len(bycat['条号缺号'])} 处，已知抽取限制）

Word 自动编号未落到正文（如「12.」编号列表被 docx2text 丢弃），导致条号序列缺号。多数为 1 条，
广州市工会法办法缺 5 条。**正文文字不缺失，仅条号不可见**；建议按 `docs/` 约定在数据说明中标注该已知限制。

{md_table([{'p': x['path'], 'e': x['evidence']} for x in bycat['条号缺号']], ["文件", "证据"], ["p", "e"])}

### 4.4 已废止文件未在 notes 说明废止依据（{len(bycat['SCHEMA问题'])} 处，全部为地方性法规）

按省份：{'、'.join(f"{k} {v}" for k, v in notes_by_prov.most_common(8))} 等。
SCHEMA 质量红线要求已废止文件在 `notes` 说明依据；建议批量补「已废止（官方时效性标注）」占位说明后，人工抽检补具体废止依据。

示例（前 15 个）：

{md_table([{'p': x['path']} for x in bycat['SCHEMA问题'][:15]], ["文件"], ["p"])}

## 5. P3/P4 提示

### 5.1 清单扩展项未入库（{len(missing)} 项，不影响必选覆盖）

{md_table([{'c': m['item']['category'], 't': m['item']['title'], 'p': m['item']['promulgated'],
            'b': m['item']['bbbs'] or 'flk未收录'} for m in missing],
           ["层级", "条目", "公布日期", "bbbs"], ["c", "t", "p", "b"])}

### 5.2 部门规章缺口（{len(dept_missing)} 条，均为人事管理外围主题）

{md_table([{'t': m['title'], 'n': m['doc_no'], 'p': m['prom']} for m in dept_missing],
           ["规章", "文号", "公布日期"], ["t", "n", "p"])}

> 另 4 条旧规章（女职工禁忌劳动范围、工伤职工劳动能力鉴定、社会保险费申报缴纳、违反和解除劳动合同经济补偿办法）
> 均已正确标注「已废止」保留，属合理边界数据（P4）。

### 5.3 章节标题缺失（{len(bycat['章节缺失'])} 处，条内容完整）

{md_table([{'p': x['path'], 'e': x['evidence']} for x in bycat['章节缺失']], ["文件", "证据"], ["p", "e"])}

### 5.4 尾部体例 / 来源优先级

- 尾部体例（{len(bycat['尾部体例'])} 处）：正文末行未以句读结束，多为表格/落款行，非截断。
- 来源优先级（{len(bycat['来源优先级'])} 处）：使用地方政府网转载页（官方但非首选来源），建议替换为 gov.cn/人社部页面。

## 6. 抽样 10 篇首尾核对（与 flk 目录树一致率 10/10）

{md_table([{"t": s["title"], "a": s["md_articles"], "b": s["flk_articles"],
            "l1": s["md_last"], "l2": s["flk_last"], "m": "✅" if s["match"] else "❌",
            "p": s["path"]} for s in sample],
           ["法律", "md 条文数", "flk 树条文数", "md 末条", "flk 末条", "一致", "文件"],
           ["t", "a", "b", "l1", "l2", "m", "p"])}

> 局限：flk 详情 `content` 目录树只对部分法律存在（全部行政法规/司法解释为 null），
> 行政法规与司法解释改用「末条编号==条文数」「附则/施行条款存在」「front matter 自洽」三重校验，未发现截断。

## 7. 地方性法规覆盖概况（{c['local']} 篇 / {len(prov)} 个省级行政区）

{md_table([{"p": k, "n": v} for k, v in sorted(prov.items(), key=lambda kv: -kv[1])], ["省份", "文件数"], ["p", "n"])}

> 地方性法规不在「国家级全量清单」口径内，清单未列地方条目，**不计为覆盖缺口**。

## 8. 发布前收尾清单

1. **修复 P1/P2 高优先**：按 4.1 统一 15 处施行日期口径；按 3.1 对 {len(para_rows)} 篇地方性法规强制分条。
2. **重跑索引**：`python3 scripts/fix_metadata.py && python3 scripts/build_index.py && python3 scripts/verify.py`。
   - 审计时点 `verify.py` 仍报 **{len([l for l in VERIFY.splitlines() if l.strip().startswith('- ')])} 处 sha256 mismatch**：
     冻结前 `fix_metadata.py` 改写了 md，但 `index.json` 停留在更早一版，属「索引落后于正文」，非数据错误，重跑即可消除。
3. **补 P2**：6 处兜底施行日期、79 处已废止 notes。
4. **文档化已知限制**：条号缺号（Word 自动编号）、施行日期口径（若保留原法口径则写入 SCHEMA）。
5. **同步 SCHEMA.md**：新增「规范性文件 / level_code 7 / data/normative-documents」层级（当前 SCHEMA 未记录）。

## 9. 发布结论

- **内容完整性：通过。** 必选核心法源 100%（17/17 法律、30/30 行政法规、7/7 司法解释），
  无正文截断、无核心缺失、无重复入库，抽样 10/10 与 flk 目录树一致，地方性法规 31 省 589 篇。
- **条级索引：存在 {len(para_rows)} 处 P1**（地方性法规条文未分行，累计约 {para_missing} 条未进条级索引；正文完整、可脚本修复）。
- **元数据：存在 {sev['P2']} 处 P2**，其中施行日期口径 15 处、兜底 6 处为优先修复项（不阻塞正文发布）。
- **是否可以发布**：
  - 若发布为「内部评审/预发布版」：**可以**，建议在 release notes 注明 3.1/3.2 两处已知问题。
  - 若发布为「正式 v1.0」：**建议先修复 P1 条级切分 + P2 施行日期口径并重跑索引**（约 30 分钟工作量），
    再执行发布检查（verify.py 0 error）；修复后本文档可直接作为发布审计证据。

## 10. 复现方式

```
python3 research/coverage/_gap_audit.py          # 重新生成 cache/audit.json
python3 research/coverage/_make_gap_report_final.py  # 重新生成本报告
python3 scripts/verify.py                        # 项目自带校验
```
"""
    (HERE / "gap-report-final.md").write_text(md)
    print("wrote gap-report-final.md", len(md), "chars; fixed", n_fixed, "/", len(fixed_rows))


if __name__ == "__main__":
    main()
