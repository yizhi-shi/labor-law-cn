# 数据规范（SCHEMA）

本仓库的每一条法规在磁盘上都是一个 Markdown 文件：**YAML front matter（元数据）+ 正文**。
`scripts/build_index.py` 会扫描 `data/**/*.md`，校验 front matter，生成
`data/index.json`、`data/index.csv`、`data/INDEX.md` 与 `data/articles/<id>.json`。

新增/修改数据时**必须**符合本规范，否则 `python3 scripts/verify.py` 会报错。

## 1. 目录与层级（`level`）

| 目录 | `level` | `level_code` | 说明 |
|---|---|---|---|
| `data/laws/` | 法律 | 1 | 全国人大及其常委会制定的法律、法律解释、有关法律问题的决定 |
| `data/administrative-regulations/` | 行政法规 | 2 | 国务院制定 |
| `data/judicial-interpretations/` | 司法解释 | 3 | 最高法/最高检 |
| `data/departmental-rules/` | 部门规章 | 4 | 人社部等国务院部门 |
| `data/local-regulations/<省份>/` | 地方性法规 | 5 | 省/市人大及其常委会 |
| `data/normative-documents/` | 规范性文件 | 7 | 部门通知/意见/办法（非规章，实务参考） |
| `data/decisions/` | 修改废止决定 | 6 | 单行的修改、废止决定 |

文件名建议：`<法规标题>-<公布年份>.md`，例如 `中华人民共和国劳动法-2018.md`。允许中文文件名。

## 2. Front matter 字段

```yaml
---
id: flk-ff8080816f135f46016f20f16ee11737   # 必填，全局唯一。flk 数据用 flk-<bbbs>；其他来源自拟稳定 id
title: 中华人民共和国劳动法                 # 必填，官方全称
short_title: 劳动法                          # 常用简称，没有则与 title 相同
level: 法律                                  # 必填，见上表
level_code: 1                                # 必填
issuer: 全国人民代表大会常务委员会          # 必填，制定/发布机关
doc_number: ""                               # 发文字号/令号，如 劳部发〔1994〕489号；没有留空
promulgated: 2018-12-29                      # 必填，公布日期 YYYY-MM-DD
effective: 2018-12-29                        # 必填，施行日期 YYYY-MM-DD；未知填 promulgated
status: 有效                                 # 必填：有效|已修改|已废止|尚未生效
status_code: 3                               # 必填：1已废止 2已修改 3有效 4尚未生效
category: 社会法                             # 法律分类（社会法/行政法/经济法/…）；部门规章填 部门规章
doc_type: 法律                               # 法律|行政法规|司法解释|部门规章|地方性法规|修改废止决定
province: ""                                 # 地方性法规必填（如 北京市），其它留空
topics: [劳动基准, 劳动合同]                 # 必填，1-4 个主题标签，见 docs/02-劳动法知识地图.md
source: https://flk.npc.gov.cn/detail?id=... # 必填，权威来源 URL
source_name: 国家法律法规数据库              # 必填
retrieved: 2026-11-10                        # 必填，抓取日期
sha256: <正文 md 的 sha256>                  # build_index.py 自动回填，可留空
chars: 12000                                 # 自动回填
articles: 107                                # 自动回填（解析出的条文数）
version_group: 中华人民共和国劳动法          # 同一条法规的不同版本用同一个值，便于沿革检索
version_note: "2018年第二次修正"             # 版本说明，没有留空
related: []                                  # 相关文件 id 列表（如实施条例、修改决定）
notes: ""                                    # 备注（如“部分条款被××废止”）
---
```

`sha256/chars/articles` 由 `build_index.py` 自动计算并写回 front matter；抓取脚本可留空。

## 3. 正文格式

- 第一行是 `# <title>`。
- 段落之间空一行；条文以 `第X条` 开头，一章一条、一节一标题。
- 章标题转成 `## 第X章 …`，节标题转成 `### 第X节 …`（`scripts/docx2md.py` 自动处理）。
- 保留官方题注（通过/修正/施行日期那段括号说明），放在正文标题之后。
- 不要手工改写条文文字；只做标点空格、换行、标题层级等版式归一化。
- 官方原文中的全角空格可保留；不要新增解释性文字到正文（解释写进 `notes` 或 docs）。

## 4. 抓取来源优先级

1. **国家法律法规数据库** `flk.npc.gov.cn`（法律/行政法规/司法解释/地方性法规/修改废止决定）
2. **人社部官网** `www.mohrss.gov.cn`（部门规章、规范性文件）
3. 国务院政策文件库 `www.gov.cn`（补充）
4. 最高法/最高检官网（补充司法解释）

每条数据必须能通过 `source` 回溯到官方页面；禁止使用商业法律数据库或二手转载作为正文来源。

## 5. 主题标签（`topics`）

固定取值（可多选，见 `docs/02-劳动法知识地图.md`）：

```
劳动基准   劳动合同   集体合同与工会   就业促进   职业培训
劳动安全卫生   特殊群体保护   社会保险   工资保障   劳动争议处理
劳动保障监察   新就业形态   人事关系   涉外用工   综合/其他
```

## 6. 质量红线

- 正文不得为空、不得截断；一篇法规一个文件。
- `status` 必须与 flk 的“时效性”一致；已废止文件保留，但在 `notes` 说明废止依据。
- 同一 `version_group` 的多个版本，`title` 相同、公布日期不同，文件名带年份区分。
- 抓取脚本必须可重跑（幂等）；已存在且校验通过的文件默认跳过。
