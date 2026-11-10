#!/usr/bin/env python3
"""阶段B：把 data/ 下已落盘的 md 与 checklist 基线（items.json + 人社部规章库 + flk 目录树）
逐项比对，输出结构化审计结果 cache/audit.json，供 gap-report.md 使用。

只读 data/，只写 research/coverage/。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
from docx2md import cn2int  # noqa: E402

from _mohrss_rules import RULES as MOHRSS_RULES  # noqa: E402

DATA = ROOT / "data"
_ITEMS_DOC = json.loads((HERE / "items.json").read_text())
ITEMS = _ITEMS_DOC["items"]
HIST = _ITEMS_DOC["historical"]
TREES = {t["b"]: t for t in json.loads((HERE / "cache/flk_trees.json").read_text())}

SXX = {1: "已废止", 2: "已修改", 3: "有效", 4: "尚未生效"}
DIR_LEVEL = {
    "laws": ("法律", 1),
    "administrative-regulations": ("行政法规", 2),
    "judicial-interpretations": ("司法解释", 3),
    "departmental-rules": ("部门规章", 4),
    "local-regulations": ("地方性法规", 5),
    "decisions": ("修改废止决定", 6),
    "normative-documents": ("规范性文件", 7),
}
REQ_FIELDS = ["id", "title", "level", "level_code", "issuer", "promulgated", "effective",
              "status", "status_code", "category", "doc_type", "topics", "source",
              "source_name", "retrieved"]
TOPIC_SET = {
    "劳动基准", "劳动合同", "集体合同与工会", "就业促进", "职业培训", "劳动安全卫生",
    "特殊群体保护", "社会保险", "工资保障", "劳动争议处理", "劳动保障监察",
    "新就业形态", "人事关系", "涉外用工", "综合/其他",
}
AUTH_DOMAINS = ("https://flk.npc.gov.cn", "https://www.mohrss.gov.cn", "http://www.mohrss.gov.cn",
                "https://www.gov.cn", "http://www.gov.cn")
RE_ART = re.compile(r"^第([一二三四五六七八九十百千零〇两]+)条(?=[\s　]|$)")
RE_ART_ANY = re.compile(r"第([一二三四五六七八九十百千零〇两]+)条(?=[\s　]|$)")
RE_CH = re.compile(r"^#{2,3}\s+(第[一二三四五六七八九十百千零〇两]+[章节编].*)$")
RE_CN_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
RE_EFF = re.compile(r"自\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*起?\s*(?:施行|实施)")
TERMINAL = "。！？；：”》」』）)…"


def norm_title(t: str) -> str:
    t = re.sub(r"\s+", "", t or "")
    return t.replace("（", "(").replace("）", ")")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def parse_file(p: Path) -> dict:
    raw = p.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    fm, body = {}, raw
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception as e:  # noqa: BLE001
            fm = {"__yaml_error__": str(e)}
        body = m.group(2)
    return {"path": str(p.relative_to(ROOT)), "fm": fm, "body": body}


def analyse(rec: dict) -> None:
    fm, body = rec["fm"], rec["body"]
    lines = body.splitlines()
    first_line = next((ln for ln in lines if ln.strip()), "")
    arts, inline_arts, chapters = [], [], []
    for ln in lines:
        s = ln.strip()
        ma = RE_ART.match(s)
        if ma:
            try:
                arts.append(cn2int(ma.group(1)))
            except ValueError:
                pass
        for mm in RE_ART_ANY.finditer(s):
            try:
                inline_arts.append(cn2int(mm.group(1)))
            except ValueError:
                pass
        mc = RE_CH.match(s)
        if mc:
            chapters.append(mc.group(1).strip())
    nonempty = [ln for ln in lines if ln.strip()]
    last = nonempty[-1].strip() if nonempty else ""
    missing_nums = []
    if arts:
        missing_nums = [i for i in range(1, max(arts) + 1) if i not in arts]
    eff_dates = ["%s-%02d-%02d" % (y, int(m), int(d)) for y, m, d in
                 [g for g in (mm.groups() for mm in RE_EFF.finditer(body))]]
    note_date = None
    mn = re.search(r"[（(](\d{4})年(\d{1,2})月(\d{1,2})日[^）)]{0,40}?(?:公布|发布|通过)", body[:1200])
    if mn:
        note_date = "%s-%02d-%02d" % (mn.group(1), int(mn.group(2)), int(mn.group(3)))
    rec["stats"] = {
        "chars_body": len(body),
        "eff_dates_in_text": eff_dates,
        "note_date": note_date,
        "is_revised": bool(re.search(r"(修正|修订|修改)", body[:1400])),
        "has_first_article": "第一条" in body,
        "has_ch1": any(c.startswith("第一章") for c in chapters),
        "chars_nows": len(re.sub(r"\s", "", body)),
        "articles_parsed": len(arts),
        "articles_max": max(arts) if arts else 0,
        "articles_any": len(set(inline_arts)),
        "articles_any_nums": sorted(set(inline_arts)),
        "articles_dup": len(arts) - len(set(arts)),
        "missing_nums": missing_nums,
        "inline_arts": len(inline_arts),
        "first_line": first_line,
        "last_line": last[:150],
        "ends_terminal": bool(last) and last[-1] in TERMINAL,
        "chapters": chapters,
        "body_head": "\n".join(nonempty[:4])[:300],
        "body_tail": "\n".join(nonempty[-3:])[-300:],
    }
    return rec


def main() -> None:
    files = []
    for sub, (level, code) in DIR_LEVEL.items():
        base = DATA / sub
        if not base.exists():
            continue
        it = base.rglob("*.md") if sub == "local-regulations" else base.glob("*.md")
        for p in sorted(it):
            rec = analyse(parse_file(p))
            rec["dir"] = sub
            rec["expected_level"] = level
            rec["expected_level_code"] = code
            rec["province_dir"] = p.parent.name if sub == "local-regulations" else ""
            files.append(rec)

    findings: list[dict] = []

    def add(sev, cat, path, msg, evidence=""):
        findings.append({"severity": sev, "category": cat, "path": path,
                         "message": msg, "evidence": evidence})

    by_id: dict[str, list] = defaultdict(list)
    by_title: dict[str, list] = defaultdict(list)
    for f in files:
        if f["fm"].get("id"):
            by_id[str(f["fm"]["id"])].append(f)
        by_title[norm_title(str(f["fm"].get("title", "")))].append(f)

    # ---------- 1. checklist -> data ----------
    missing = []
    for it in ITEMS:
        if it["category"] == "部门规章":
            continue
        hit = None
        if it.get("bbbs"):
            for c in by_id.get("flk-" + it["bbbs"], []):
                if norm_title(str(c["fm"].get("title"))) == norm_title(it["title"]):
                    hit = c
                    break
            if not hit:
                for c in by_title.get(norm_title(it["title"]), []):
                    if str(c["fm"].get("promulgated")) == it["promulgated"]:
                        hit = c
                        break
        if hit is None:
            # 扩展项：允许以同标题的任何版本存在（说明已有覆盖）
            alt = by_title.get(norm_title(it["title"]), [])
            hit = alt[0] if alt else None
        if hit:
            hit["checklist"] = it
        else:
            sev = "P1" if it["required"] else "P3"
            missing.append({"severity": sev, "item": it})
            add(sev, "缺失项", "—",
                f"清单{'必选' if it['required'] else '扩展'}条目《{it['title']}》（{it['category']}，{it['promulgated']}）未在 data/ 找到",
                f"bbbs={it['bbbs'] or 'flk未收录'}")

    # ---------- 2. 命中项字段比对 ----------
    for f in files:
        it = f.get("checklist")
        fm, path, st = f["fm"], f["path"], f["stats"]
        if it:
            if norm_title(str(fm.get("title"))) != norm_title(it["title"]):
                add("P2", "标题错误", path, "title 与 flk/清单不一致",
                    f"文件={fm.get('title')!r} 期望={it['title']!r}")
            exp = it["sxx"]
            got = fm.get("status_code")
            if got != exp:
                add("P1", "状态错误", path, "status_code 与 flk sxx 不一致",
                    f"文件={fm.get('status')}/{got} 期望={SXX.get(exp)}/{exp} bbbs={it.get('bbbs')}")
            elif fm.get("status") != SXX.get(exp):
                add("P2", "状态错误", path, "status 文本与 status_code 不匹配", f"{fm.get('status')} vs {got}")
            if str(fm.get("promulgated")) != it["promulgated"]:
                add("P1", "日期错误", path, "公布日期与 flk gbrq 不一致",
                    f"文件={fm.get('promulgated')} flk={it['promulgated']} bbbs={it.get('bbbs')}")
            if it["effective"] and str(fm.get("effective")) != it["effective"]:
                if str(fm.get("effective")) == str(fm.get("promulgated")):
                    add("P2", "日期待修正", path, "施行日期以公布日填充，与官方施行日不符",
                        f"文件={fm.get('effective')} 官方={it['effective']}（SCHEMA 允许未知填公布日，但与事实不符）")
                else:
                    add("P2", "日期错误", path, "施行日期被写成正文附则的「原始施行日」，与 flk 现行版本施行日不一致（口径冲突）",
                        f"文件={fm.get('effective')} 官方(flk sxrq)={it['effective']} bbbs={it.get('bbbs')}")
            if it["issuer"] and norm_title(str(fm.get("issuer"))) != norm_title(it["issuer"]):
                add("P2", "制定机关错误", path, "issuer 与 flk zdjgName 不一致",
                    f"文件={fm.get('issuer')!r} flk={it['issuer']!r}")
        if (not it and st["eff_dates_in_text"]
                and str(fm.get("effective")) not in st["eff_dates_in_text"]):
            txt = st["eff_dates_in_text"][-1]
            if f["dir"] == "departmental-rules":
                add("P2", "日期待修正", path, "施行日期与正文末条载明的日期不一致（正文更可信，建议修正）",
                    f"字段={fm.get('effective')} 正文载明={txt} 行文=第{st['articles_max']}条附则")
            elif (f["dir"] == "departmental-rules" and not st["is_revised"]
                  and str(fm.get("effective")) == str(fm.get("promulgated"))):
                add("P2", "日期待修正", path, "施行日期以公布日兜底，与正文末条载明不一致",
                    f"字段={fm.get('effective')} 正文最末载明={txt}")
        if fm.get("level") != f["expected_level"] or fm.get("level_code") != f["expected_level_code"]:
            add("P1", "层级错误", path, "level/level_code 与所在目录不匹配",
                f"{fm.get('level')}/{fm.get('level_code')} 目录={f['expected_level']}/{f['expected_level_code']}")
        if fm.get("doc_type") and fm.get("doc_type") != f["expected_level"]:
            add("P3", "层级错误", path, "doc_type 与 level 不一致", f"{fm.get('doc_type')} vs {fm.get('level')}")
        src = str(fm.get("source") or "")
        if not src.startswith(AUTH_DOMAINS):
            if re.search(r"://([\w.-]+\.)?gov\.cn/", src):
                add("P3", "来源优先级", path, "source 为地方政府/部门网站（官方，但非 SCHEMA 首选来源）", src)
            else:
                add("P2", "来源问题", path, "source 非官方 gov.cn 域名", src)
        elif src.startswith("https://flk.npc.gov.cn") and it and it.get("bbbs") and it["bbbs"] not in src:
            add("P2", "来源问题", path, "flk source 未带 bbbs", src)
        tp = fm.get("topics") or []
        if not isinstance(tp, list) or not tp:
            add("P2", "SCHEMA问题", path, "topics 为空或格式错误", str(tp))
        else:
            bad = [t for t in tp if t not in TOPIC_SET]
            if bad:
                add("P2", "SCHEMA问题", path, "topics 含非规范标签", str(bad))
        for fld in REQ_FIELDS:
            if fm.get(fld) in (None, ""):
                add("P2", "SCHEMA问题", path, f"缺少必填字段 {fld}", "")
        if fm.get("status_code") == 1 and not str(fm.get("notes") or "").strip():
            add("P2", "SCHEMA问题", path, "已废止文件未在 notes 说明废止依据", "")
        if st["first_line"] != f"# {fm.get('title')}":
            add("P2", "正文体例", path, "正文首行不是 `# <title>`", f"首行={st['first_line']!r}")
        if isinstance(fm.get("chars"), int) and fm["chars"]:
            if fm["chars"] != st["chars_nows"] and abs(fm["chars"] - st["chars_nows"]) > 0.02 * max(fm["chars"], 1):
                add("P3", "字数不一致", path, "chars 与正文非空白字符数偏差>2%",
                    f"字段={fm['chars']} 实际非空白={st['chars_nows']}")
        if isinstance(fm.get("articles"), int) and fm["articles"] and fm["articles"] != st["articles_parsed"]:
            add("P1", "条文数不一致", path, "articles 字段与正文解析条文数不一致",
                f"字段={fm['articles']} 解析={st['articles_parsed']}")
        if fm.get("sha256") and fm["sha256"] not in (sha256(f["body"].lstrip("\n")), sha256(f["body"])):
            add("P3", "sha256不一致", path, "sha256 与正文哈希不匹配", str(fm["sha256"])[:16])
        # 条文未分行：条文最大编号 > 解析数，且缺号在正文中以行内形式出现
        all_nums = set(st["articles_any_nums"])
        if all_nums and f["dir"] not in ("decisions", "normative-documents"):
            miss = [i for i in range(1, max(all_nums) + 1) if i not in all_nums]
            if miss:
                add("P2", "条号缺号", path, "条号序列缺号（Word 自动编号未落到正文，属抽取限制）",
                    f"共缺 {len(miss)} 条：{miss[:12]}{'…' if len(miss) > 12 else ''}（最大条号 第{max(all_nums)}条）")
        if st["articles_any"] > st["articles_parsed"] and f["dir"] != "decisions":
            add("P1", "条文未分行", path,
                "条文未按行起排 → 条级解析不完整（影响 articles 索引）",
                f"行首条文={st['articles_parsed']} 正文中条号出现={st['articles_any']} "
                f"（差 {st['articles_any'] - st['articles_parsed']} 条被并入段落；正文文字未缺失）")
        if st["articles_parsed"] == 0 and fm.get("articles"):
            add("P1", "截断风险", path, "正文解析不到任何条文", "")
        if (not st["has_first_article"] and f["dir"] not in ("decisions", "normative-documents")
                and (fm.get("articles") or st["articles_parsed"] or 0) >= 5):
            add("P1", "正文开头缺失", path, "正文中完全没有「第一条」，疑似缺失第一章/总则（内容缺失）",
                f"正文首个条号=第{st['articles_min'] if 'articles_min' in st else st['articles_max']}条区域，首行={st['first_line']!r}")
        if st["has_ch1"] is False and len([c for c in st["chapters"] if "章" in c]) >= 2:
            add("P3", "章节缺失", path, "其它章存在但缺「第一章」标题（条内容完整，仅标题丢失）", "、".join(st["chapters"][:3]))
        if not st["ends_terminal"] and st["chars_body"] > 100:
            add("P3", "尾部体例", path, "正文最后一行未以句读/右引号结束（表格/日期落款常见，非截断）",
                st["last_line"][:80])
        if st["chars_body"] < 150:
            add("P3", "短文本", path, "正文极短（可能是决议/批复，需人工确认完整性）", f"chars={st['chars_body']}")
        # flk 目录树
        if it and it.get("bbbs") and it["bbbs"] in TREES:
            tree = TREES[it["bbbs"]]
            if tree["n"] > 0:
                if st["articles_parsed"] != tree["n"]:
                    add("P1", "截断风险", path, "正文条文数与 flk 目录树不一致（疑似截断/多抓）",
                        f"md={st['articles_parsed']} flk树={tree['n']} bbbs={it['bbbs']}")
                exp_last = None
                if tree["l"]:
                    try:
                        exp_last = cn2int(tree["l"][1:-1])
                    except Exception:  # noqa: BLE001
                        exp_last = None
                if exp_last and st["articles_max"] != exp_last:
                    add("P1", "截断风险", path, "正文末条编号与 flk 目录树末条不一致",
                        f"md末条=第{st['articles_max']}条 flk末条={tree['l']}")
                tree_ch = [c for c in tree["chs"] if "章" in c]
                md_ch = [c for c in st["chapters"] if "章" in c]
                if tree_ch and len(md_ch) != len(tree_ch):
                    add("P2", "章节不一致", path, "章标题数与 flk 目录树不一致",
                        f"md={len(md_ch)} flk={len(tree_ch)}")
            else:
                f["tree_absent"] = True

    # ---------- 3. 重复 ----------
    for i, lst in by_id.items():
        if len(lst) > 1:
            add("P1", "重复项", "; ".join(x["path"] for x in lst), f"同一 id 出现 {len(lst)} 次", i)
    seen_title = {}
    for f in files:
        key = (norm_title(str(f["fm"].get("title", ""))), str(f["fm"].get("promulgated", "")))
        if key in seen_title and f["dir"] != "local-regulations":
            add("P1", "重复项", f["path"], "同标题同公布日期重复", f"另见 {seen_title[key]}")
        else:
            seen_title[key] = f["path"]

    # ---------- 4. 多出文件 ----------
    checklist_titles = {norm_title(i["title"]) for i in ITEMS}
    hist_ids = {h["bbbs"] for h in HIST}
    extras = []
    for f in files:
        if f["fm"].get("checklist") or f["dir"] in ("local-regulations", "departmental-rules",
                                                    "decisions", "normative-documents"):
            continue
        fid = str(f["fm"].get("id", ""))
        if fid.startswith("flk-") and fid[4:] in hist_ids:
            continue
        if norm_title(str(f["fm"].get("title", ""))) in checklist_titles:
            continue  # 同标题的不同版本，属正常沿革
        extras.append(f["path"])
        add("P3", "多出文件", f["path"], "不在清单（含历史版本表）内，需人工确认是否应保留",
            f"title={f['fm'].get('title')} status={f['fm'].get('status')}")

    # ---------- 5. 部门规章 vs 人社部规章库 ----------
    dept = [f for f in files if f["dir"] == "departmental-rules"]
    rule_by_title = {}
    for no, title, issuer, doc_no, prom, eff, core, note in MOHRSS_RULES:
        rule_by_title.setdefault(norm_title(title), []).append(
            dict(no=no, title=title, issuer=issuer, doc_no=doc_no, prom=prom,
                 eff=eff, core=core, note=note))
    data_by_title = defaultdict(list)
    for f in dept:
        data_by_title[norm_title(str(f["fm"].get("title", "")))].append(f)

    normative_titles = {norm_title(str(f["fm"].get("title", ""))) for f in files
                        if f["dir"] == "normative-documents"}
    dept_missing = []
    for nt, infos in rule_by_title.items():
        if nt in normative_titles:
            continue  # 已按「规范性文件」层级收录，属分类口径差异而非缺失
        if nt not in data_by_title:
            info = infos[0]
            sev = "P1" if info["core"] else "P3"
            dept_missing.append({"severity": sev, **info})
            add(sev, "部门规章缺失", "—", f"人社部现行规章《{info['title']}》（{info['doc_no']}）未入库",
                f"公布 {info['prom']} 施行 {info['eff'] or '自公布之日'}")
    dept_extra = []
    for nt, fl in data_by_title.items():
        f0 = fl[0]
        if nt in rule_by_title:
            info = rule_by_title[nt][0]
            fm = f0["fm"]
            if str(fm.get("promulgated")) != info["prom"]:
                add("P2", "部门规章日期", f0["path"], "公布日期与人社部规章库不一致",
                    f"文件={fm.get('promulgated')} 规章库={info['prom']}")
            if info["eff"] and str(fm.get("effective")) != info["eff"]:
                add("P2", "部门规章日期", f0["path"], "施行日期与规章库题注不一致",
                    f"文件={fm.get('effective')} 规章库={info['eff']}")
            if fm.get("status_code") != 3:
                add("P2", "部门规章状态", f0["path"], "规章库列现行有效，但文件非有效状态",
                    str(fm.get("status")))
        else:
            dept_extra.append(f0["path"])
            if f0["fm"].get("status_code") == 1:
                add("P4", "部门规章多出", f0["path"],
                    "不在人社部规章库现行清单内，但文件已正确标注已废止（保留可接受）",
                    f"title={f0['fm'].get('title')}")
            else:
                add("P2", "部门规章多出", f0["path"],
                    "不在人社部规章库现行 76 条清单内且未标已废止，状态存疑",
                    f"title={f0['fm'].get('title')} status={f0['fm'].get('status')}")

    # ---------- 6. 地方性法规 ----------
    local = [f for f in files if f["dir"] == "local-regulations"]
    prov = Counter(f["province_dir"] for f in local)
    for f in local:
        if f["fm"].get("province") != f["province_dir"]:
            add("P2", "地方层级", f["path"], "province 字段与目录名不一致",
                f"{f['fm'].get('province')} vs {f['province_dir']}")
        if f["fm"].get("level_code") != 5:
            add("P1", "层级错误", f["path"], "地方性法规 level_code 应为 5", str(f["fm"].get("level_code")))

    # ---------- 7. 决定 / 规范性文件 ----------
    decisions = [f for f in files if f["dir"] == "decisions"]
    normative = [f for f in files if f["dir"] == "normative-documents"]
    for f in normative:
        if f["fm"].get("level_code") != 7:
            add("P2", "层级错误", f["path"], "规范性文件 level_code 应为 7", str(f["fm"].get("level_code")))

    # ---------- 8. 抽样 10 篇（法律，有 flk 目录树）----------
    sample = []
    pool = [f for f in files if f["dir"] == "laws" and f.get("checklist")
            and f["checklist"].get("bbbs") in TREES and TREES[f["checklist"]["bbbs"]]["n"] > 0]
    seen_b = set()
    for f in pool:
        b = f["checklist"]["bbbs"]
        if b in seen_b:
            continue
        seen_b.add(b)
        sample.append(f)
        if len(sample) >= 10:
            break
    sample_rows = []
    for f in sample:
        it = f["checklist"]
        tree = TREES[it["bbbs"]]
        st = f["stats"]
        ok = st["articles_parsed"] == tree["n"] and st["articles_max"] == cn2int(tree["l"][1:-1])
        sample_rows.append({
            "path": f["path"], "title": it["title"], "bbbs": it["bbbs"],
            "md_articles": st["articles_parsed"], "flk_articles": tree["n"],
            "md_last": f"第{st['articles_max']}条", "flk_last": tree["l"],
            "md_first_article": st["body_head"].splitlines()[2][:40] if len(st["body_head"].splitlines()) > 2 else "",
            "md_first_line": st["body_head"].splitlines()[0] if st["body_head"] else "",
            "md_tail": st["body_tail"][-160:], "match": ok,
        })

    import datetime as _dt
    mtimes = [Path(ROOT / f["path"]).stat().st_mtime for f in files]
    cov = {}
    for it in ITEMS:
        if it["category"] == "部门规章":
            continue
        d = cov.setdefault(it["category"], {"required": 0, "required_matched": 0,
                                            "total": 0, "total_matched": 0})
        hit = any(f.get("checklist") is it for f in files)
        d["total"] += 1
        d["total_matched"] += 1 if hit else 0
        if it["required"]:
            d["required"] += 1
            d["required_matched"] += 1 if hit else 0
    cov["部门规章"] = {"required": len(rule_by_title), "required_matched": len(rule_by_title) - len(dept_missing),
                       "total": len(rule_by_title), "total_matched": len(rule_by_title) - len(dept_missing)}
    audit = {
        "generated": "2026-11-10",
        "coverage": cov,
        "snapshot_mtime": _dt.datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d %H:%M:%S") if mtimes else "",
        "total_files": len(files),
        "counts": {"laws": sum(1 for f in files if f["dir"] == "laws"),
                   "admin": sum(1 for f in files if f["dir"] == "administrative-regulations"),
                   "judicial": sum(1 for f in files if f["dir"] == "judicial-interpretations"),
                   "departmental": len(dept), "local": len(local), "decisions": len(decisions),
                   "normative": sum(1 for f in files if f["dir"] == "normative-documents")},
        "checklist_total": len(ITEMS),
        "checklist_required": sum(1 for i in ITEMS if i["required"]),
        "required_missing": [m["item"]["title"] for m in missing if m["severity"] == "P1"],
        "missing": missing,
        "dept_missing": dept_missing,
        "dept_extra": dept_extra,
        "local_provinces": dict(prov),
        "normative": [f["path"] for f in normative],
        "tree_available": sum(1 for f in files if f.get("checklist") and not f.get("tree_absent")
                              and f["checklist"].get("bbbs") in TREES),
        "tree_absent_laws": [f["path"] for f in files if f.get("tree_absent")],
        "sample": sample_rows,
        "findings": findings,
        "files": [{"path": f["path"], "title": f["fm"].get("title"), "status": f["fm"].get("status"),
                   "bbbs": (f.get("checklist") or {}).get("bbbs"),
                   "articles_field": f["fm"].get("articles"),
                   "articles_parsed": f["stats"]["articles_parsed"],
                   "articles_max": f["stats"]["articles_max"],
                   "chars": f["stats"]["chars_nows"],
                   "tree": (TREES.get(((f.get("checklist") or {}).get("bbbs") or ""), {}) or {}).get("n"),
                   "tree_absent": f.get("tree_absent", False),
                   "level": f["fm"].get("level")} for f in files],
    }
    (HERE / "cache/audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=1))
    c = Counter((x["severity"], x["category"]) for x in findings)
    print(json.dumps(audit["counts"], ensure_ascii=False))
    print("missing checklist:", len(missing), "| dept missing:", len(dept_missing), "dept extra:", len(dept_extra))
    print("local provinces:", dict(prov))
    print("sample match:", Counter(r["match"] for r in sample_rows))
    for (sev, cat), n in sorted(c.items()):
        print(f"  {sev} {cat}: {n}")


if __name__ == "__main__":
    main()
