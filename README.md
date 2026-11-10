# 中国劳动法全量法规库 · labor-law-cn

> 一个面向 AI agent 的**中国劳动法全量语料库 + 检索技能**：780 篇官方法规全文、结构化索引、
> 离线全文检索、年龄维度标签、争议类型/证据/文书工作流，开箱即用。

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](./LICENSE)
[![Data: Official](https://img.shields.io/badge/Data-flk.npc.gov.cn-blue.svg)](https://flk.npc.gov.cn)
[![Coverage: National + Local](https://img.shields.io/badge/Coverage-National%20%2B%20Local-success.svg)](#-覆盖范围)
[![Age: 16--65%2B](https://img.shields.io/badge/Age-16--65%2B-important.svg)](docs/07-年龄维度全生命周期.md)

---

## 这是什么

劳动法不是一个法典，而是由**法律、行政法规、司法解释、部门规章、地方性法规、修改废止决定**
以及大量规范性文件构成的规范群。多数 AI 回答劳动法问题时，靠的是模型记忆——条号记错、版本过时、
把地方规定当全国规定，是常见问题。

本项目把**官方原文**下载、清洗、结构化，做成一个 agent 可以直接检索、引用、核对时效性的技能：

- **全量语料**：国家层面法律/行政法规/司法解释/部门规章 + 31 个省级行政区的地方性法规；
- **结构化索引**：每条法规一个 Markdown（YAML front matter + 正文），含层级、机关、公布/施行日期、
  时效性、主题、年龄维度、官方来源、sha256、条文拆分 JSON；
- **离线检索**：`search.py` 支持关键词、条号、层级、时效、地域、年龄维度过滤，输出条文片段与出处；
- **可校验**：`verify.py` 校验哈希、条文数、核心法规齐备、来源合法性；
- **可复现**：抓取脚本可重跑（幂等、限流、WAF 处理），`manifest.json` 记录每篇来源与校验信息；
- **实务工作流**：14 类争议的举证要点、证据分级、法律意见书/仲裁申请书/律师函/工伤材料模板。

## 为什么比同类项目更完整

| 维度 | 常见做法 | 本项目 |
|---|---|---|
| 法条数量 | 内置 7-10 部核心法律 | **780 篇**：法律 37、行政法规 43、司法解释 19、部门规章 71、规范性文件 10、地方性法规 589、修改废止决定 11 |
| 时效性 | 只收现行版，或混用旧版 | 收录历史版本并标注 `有效/已修改/已废止/尚未生效`，同一法规 `version_group` 互链 |
| 地方规定 | 基本没有 | 31 个省级行政区劳动/工资/社保/工会/安全/女职工等地方性法规 |
| 检索方式 | 让模型自己读全文 | 结构化索引 + CLI 检索 + 条号定位 + JSON 输出，agent 可直接调用 |
| 年龄覆盖 | 零散提及 | **全生命周期**：童工、未成年工、青年、育龄女性、中年、临近退休、超龄/退休返聘、高龄、实习生/学徒 |
| 可验证 | 无 | sha256、条文数、核心法规清单、来源域名、`verify.py` + 测试 |
| 实务产出 | 只有法条 | 争议类型、举证要点、证据分级、意见书/仲裁/律师函/工伤模板、示例问答 |

## 覆盖范围

| 层级 | 内容 | 数量 |
|---|---|---|
| 法律 | 劳动法、劳动合同法、就业促进法、劳动争议调解仲裁法、社会保险法、工会法、安全生产法、职业病防治法、妇女权益保障法、残疾人保障法、未成年人保护法、老年人权益保障法、矿山安全法、特种设备安全法、危险化学品安全法、医疗保障法、职业教育法、人口与计划生育法、煤炭法、建筑法、退役军人保障法及相关批准决议 | 37 |
| 行政法规 | 劳动合同法实施条例、劳动保障监察条例、工伤保险条例、失业保险条例、社保费征缴/经办条例、职工带薪年休假条例、女职工劳动保护特别规定、禁止使用童工规定、使用有毒物品作业场所劳动保护条例、矿山安全法实施条例、安全生产许可证条例、建设工程安全生产管理条例、煤矿安全生产条例、危化品条例、特种设备安全监察条例、工资总额组成规定、职工工作时间规定、住房公积金条例、残疾人就业条例、人力资源市场暂行条例、保障农民工工资支付条例、尘肺病防治条例、生产安全事故条例、事业单位人事管理条例、工人退休退职/职工探亲规定等 | 43 |
| 司法解释 | 劳动争议解释（一）（二）及历史解释、工会法解释、工伤保险行政案件规定、拒不支付劳动报酬刑事案件解释、人事争议规定/批复等 | 19 |
| 部门规章 | 人社部现行及历史部令 71 件（工资支付、最低工资、集体合同、劳务派遣、工伤认定、年休假实施办法、仲裁办案规则、社保经办、超龄劳动者规定等） | 71 |
| 地方性法规 | 31 个省级行政区的劳动、工资支付、社保、工会、劳动监察、安全生产、职业病、女职工保护等条例 | 589 |
| 规范性文件 | 劳动关系认定、工资折算、新就业形态、非全日制、实习管理等 | 10 |
| 修改/废止决定 | 工会法、安全生产法、人口与计划生育法、未成年人保护法、延迟退休、劳动教养废止等 | 11 |

> 精确数量以 `python3 scripts/search.py --stats` 为准（索引随数据更新）。

## 快速开始

```bash
git clone https://github.com/yizhi-shi/labor-law-cn.git
cd labor-law-cn

# 规模统计
python3 scripts/search.py --stats

# 主题检索（默认 AND，按标题/条文相关度排序）
python3 scripts/search.py 加班费 --status 有效
python3 scripts/search.py 竞业限制 经济补偿 --level 法律 --status 有效
python3 scripts/search.py 工伤 认定 --topic 社会保险

# 单篇 + 条文原文
python3 scripts/search.py --doc 劳动合同法 --article 39
python3 scripts/search.py --doc 中华人民共和国劳动法 --article 44

# 地方规定 / 年龄维度
python3 scripts/search.py 工资支付 --province 广东省
python3 scripts/search.py --age 超龄
python3 scripts/search.py --age 16-18

# JSON（给程序/子 agent）
python3 scripts/search.py 拖欠工资 --status 有效 --json
```

## 作为 Agent Skill 安装

```bash
# 安装到 Claude Code / DSH 的技能目录
bash scripts/install.sh

# 或手动
cp -r labor-law-cn ~/.claude/skills/labor-law-cn
```

安装后，agent 读到 `SKILL.md` 即可按“检索 → 取条文 → 核时效 → 引用”的流程工作；
技能内所有命令都在技能根目录执行。

## 目录结构

```
SKILL.md                    技能入口（agent 先读这个）
SCHEMA.md                   数据规范
README.md
LICENSE                     CC BY 4.0（数据与文档）
LICENSE-CODE                MIT（脚本）
data/
  index.json / index.csv    主索引 + 表格版
  INDEX.md                  人读目录
  stats.json                统计
  laws/                     法律
  administrative-regulations/ 行政法规
  judicial-interpretations/ 司法解释
  departmental-rules/       部门规章
  normative-documents/      规范性文件（补充）
  local-regulations/<省>/   地方性法规
  decisions/                修改/废止决定
  articles/<id>.json        按“第X条”拆分的条文
  manifest.json             抓取清单与校验记录
docs/
  00-使用指南.md
  01-效力层级与适用规则.md
  02-劳动法知识地图.md
  03-高频问题条文速查.md
  04-数据来源与校验.md
  05-更新与维护.md
  06-免责声明.md
  07-年龄维度全生命周期.md
  08-争议类型与举证要点.md
  09-咨询流程与文书指引.md
templates/                  意见书/仲裁申请/被迫解除/律师函/证据清单/工伤材料
examples/                   三个可复现的问答示例
scripts/                    fetch / build / search / verify / install
tests/                      冒烟测试
raw/                        官方原始文件（docx / html，供复现）
```

## 数据来源与合规

- **国家法律法规数据库**（https://flk.npc.gov.cn）：法律、行政法规、司法解释、地方性法规、
  修改/废止决定的正文与效力状态；
- **人力资源和社会保障部**（https://www.mohrss.gov.cn）：部门规章、部令；
- **中国政府网/地方政府门户**：flk 未收录的少数国务院文件（1978 年退休退职办法、1981 年探亲规定等）。

正文均来自官方发布的 docx 原件或官方网页，不使用商业数据库或二手转载。根据《著作权法》，
法律、法规等官方文件不受著作权保护；本项目的整理、索引、注释与代码以 CC BY 4.0 / MIT 开放。

## 维护

```bash
python3 scripts/fetch_national.py   # 国家层面（幂等，带限流/WAF 处理）
python3 scripts/fetch_mohrss.py     # 人社部规章
python3 scripts/fetch_local.py      # 地方性法规
python3 scripts/fetch_gov_supplement.py
python3 scripts/build_index.py      # 重建索引
python3 scripts/verify.py           # 校验
pytest -q                           # 测试（可选）
```

详见 [docs/05-更新与维护.md](docs/05-更新与维护.md)。

## 局限

- 地方**政府规章**、地方规范性文件（红头文件）未全量收录；
- 部门规范性文件仅收录少量核心文件（劳动关系认定、工资折算、新业态、实习管理）；
- 指导性案例、典型案例、会议纪要、国际劳工公约不在语料内；
- 法规会更新，重要结论请回源核对（`source` 字段）或重跑抓取脚本；
- 本项目提供规范依据与文书草稿，**不构成法律意见**。

## 致谢

- 感谢 [jerry046918/labor_rights_skills](https://github.com/jerry046918/labor_rights_skills)：
  本项目的“争议类型—证据收集—法律意见书—行动文书”工作流、证据分级与实务模板设计，参考了该项目的
  思路与结构；本项目在其基础上扩展为**全量法规语料 + 结构化检索 + 年龄维度 + 可校验数据管线**，
  两者可以配合使用（本项目负责“找对法条”，该项目擅长“咨询流程与录音证据处理”）。
- 感谢国家法律法规数据库、人力资源和社会保障部提供权威、公开的法规数据。
- 感谢所有为劳动法知识普及做出贡献的法律工作者。

## 免责声明

本项目收录的法规文本来自官方公开渠道，力求完整准确，但不对排版、转换过程中可能存在的误差承担责任；
一切以官方正式文本为准。本项目不构成法律意见，具体案件请咨询执业律师或当地人社/仲裁机构。
使用本项目产生的法律判断与后果由使用者自行承担。

## License

- 数据与文档：[CC BY 4.0](LICENSE)
- 代码：[MIT](LICENSE-CODE)
