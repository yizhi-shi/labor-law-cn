#!/usr/bin/env python3
"""抓取人力资源社会保障部（ mohrss ）部门规章全文并写成规范化 Markdown。

数据源
------
人社部官网 www.mohrss.gov.cn 被 WAF 拦截（返回 ~1KB 脚本页），但站点镜像 IP
http://114.255.111.133/ 可以正常访问同一路径，因此本脚本对镜像抓取：

  规章列表   /xxgk2020/gzk/gz/index.html          （index_1.html … 分页）
  部门规章   /xxgk2020/fdzdgknr/zcfg/bmgz/index.html（index_1.html … 分页）

“规章”列表是部机关整理的现行有效规章（约 75 条），详情页版式统一、正文从
“第一条”开始；“部门规章”列表（政策法规库）额外给出索引号/分类/发布单位/
发文字号/是否有效等元数据，并含少量单独发布的修改、废止决定。

少数已废止但仍在劳动法研究中常用的文件（社会保险费申报缴纳管理规定、
工伤职工劳动能力鉴定管理办法、违反和解除劳动合同的经济补偿办法、女职工
禁忌劳动范围的规定）已从部官网规章库下线，按其“效力状态”从中国政府网 /
省级人社部门政府网站取原文，见 SPECIALS 表。

产物
----
  data/departmental-rules/<标题>-<公布年份>.md   front matter + 正文（部门规章，level_code 4）
  data/normative-documents/<标题>-<公布年份>.md  front matter + 正文（规范性文件，level_code 7）
  raw/mohrss/<页面id>.html                        原文 HTML/DOCX 快照
  research/mohrss/index.json                      索引（可回溯、带 sha256/条数）

脚本可重跑：目录/索引每次重建，已存在的 md 默认跳过；已缓存的 HTML 快照
直接复用，不重复下载；请求限速 0.5–1s 并带重试。

用法
----
  python3 scripts/fetch_mohrss.py                 # 全量抓取（默认）
  python3 scripts/fetch_mohrss.py --force         # 重新解析并覆盖已有文件
  python3 scripts/fetch_mohrss.py --only 工资支付暂行规定
  python3 scripts/fetch_mohrss.py --dry-run       # 只解析、打印报告，不写文件
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT / "data" / "departmental-rules"
RAW_DIR = PROJECT / "raw" / "mohrss"
RESEARCH_DIR = PROJECT / "research" / "mohrss"

MIRROR = "http://114.255.111.133"
CANONICAL = "https://www.mohrss.gov.cn"
LIST_GZ = "/xxgk2020/gzk/gz"
LIST_BMGZ = "/xxgk2020/fdzdgknr/zcfg/bmgz"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
RETRIEVED = "2026-11-10"
STATUS_CODE = {"已废止": 1, "已修改": 2, "有效": 3, "尚未生效": 4}

# 与劳动关系、劳动人事管理不直接相关的规章，不收录。
EXCLUDE_TITLES = {
    # 按“一、二、三”分项、无“第X条”的文件改由 NORMATIVE_DOCS / SPECIALS 专项收录
    "城镇集体所有制企业工资同经济效益挂钩办法",
    "机关、事业单位工人技术等级岗位考核暂行办法",
    "企事业单位评聘专业技术职务若干问题暂行规定",
    "关于《中外合资人才中介机构管理暂行规定》的补充规定",
    # 与劳动关系不直接相关的人事管理规章
    "关于调整使用不当,不能充分发挥专长的留学回国人员工作的办法",
    "人事部关于改进国务院各部门从北京外调（迁）入有关人员审批办法的暂行规定",
    "干部调配工作规定",
    "机关、事业单位增人计划卡暂行管理办法",
    "全民所有制机关、事业单位职工人数和工资总额计划管理暂行办法",
}

# 单独发布的修改/废止决定不属于“部门规章”正文，归 data/decisions/（本脚本不写）。
DECISION_RE = re.compile(r"(?:修改|废止|宣布失效).{0,30}决定$")

# 主题标签，按序匹配，最多取 4 个（取值见 SCHEMA.md §5 / docs/02-劳动法知识地图.md）
TOPIC_RULES: list[tuple[str, str]] = [
    ("社会保险", r"社会保险|养老保险|医疗保险|工伤保险|失业保险|生育保险|企业年金|社保基金|社会保险费|劳动能力鉴定|供养亲属|工伤"),
    ("工资保障", r"工资|最低工资|经济补偿|赔偿|欠薪|农民工"),
    ("集体合同与工会", r"集体合同|集体协商|工会"),
    ("劳动合同", r"劳动合同|劳务派遣|裁减|经济性裁员|用工"),
    ("就业促进", r"就业|招聘|人才市场|人力资源服务|职业介绍|中介|失业登记"),
    ("职业培训", r"职业培训|职业技能|技工学校|职业资格|专业技术资格|专业技术人员资格|技能大奖|技术能手|继续教育|技能人才"),
    ("特殊群体保护", r"未成年工|女职工|禁忌劳动|残疾人|超龄|特殊保护"),
    ("劳动基准", r"工时|工作时间|休息休假|年休假|劳动基准|劳动安全|安全卫生|医疗期|患病"),
    ("劳动争议处理", r"劳动争议|争议仲裁|仲裁|调解"),
    ("劳动保障监察", r"劳动保障监察|监察|行政处罚|听证|社会公布|失信|稽核|监督举报"),
    ("人事关系", r"事业单位|职称|人事|干部|机关|工人技术等级|公开招聘"),
    ("涉外用工", r"外国人|台湾|香港|澳门|中外合资|中外合作"),
    ("新就业形态", r"新就业形态|平台就业|网络招聘|灵活就业"),
]
TOPIC_FALLBACK = "综合/其他"

# 政府网/省级人社部门站点的补充文件（已从部规章库下线，按“已废止”收录）。
SPECIALS: list[dict] = [
    {
        "id": "mohrss-gov-2603507",
        "raw_id": "gov-2603507",
        "title": "社会保险费申报缴纳管理规定",
        "short_title": "社会保险费申报缴纳管理规定",
        "caption": "（2013年9月26日人力资源社会保障部令第20号公布　自2013年11月1日起施行）",
        "url": "https://www.gov.cn/zhengce/2013-10/31/content_2603507.htm",
        "source_name": "中国政府网（转人力资源社会保障部）",
        "issuer": "人力资源和社会保障部",
        "doc_number": "人力资源社会保障部令第20号",
        "promulgated": "2013-09-26",
        "effective": "2013-11-01",
        "status": "已废止",
        "notes": "已废止：根据2021年12月22日《人力资源社会保障部关于废止〈社会保险费申报缴纳管理规定〉的决定》（人力资源社会保障部令第46号）废止。",
    },
    {
        "id": "mohrss-gov-5711336",
        "raw_id": "gov-5711336",
        "title": "工伤职工劳动能力鉴定管理办法",
        "short_title": "工伤职工劳动能力鉴定管理办法",
        "caption": "（2014年2月20日人力资源社会保障部、国家卫生和计划生育委员会令第21号公布　根据2018年12月14日《人力资源社会保障部关于修改部分规章的决定》修订）",
        "url": "https://www.gov.cn/zhengce/2022-08/31/content_5711336.htm",
        "source_name": "中国政府网（转人力资源社会保障部）",
        "issuer": "人力资源和社会保障部、国家卫生和计划生育委员会",
        "doc_number": "人力资源社会保障部、国家卫生和计划生育委员会令第21号",
        "promulgated": "2014-02-20",
        "effective": "2014-04-01",
        "status": "已废止",
        "notes": "已废止：根据2025年5月13日《劳动能力鉴定管理办法》（人力资源社会保障部、国家卫生健康委令第55号），自2025年7月1日起本办法同时废止。",
    },
    {
        "id": "mohrss-sd-481",
        "raw_id": "sd-481",
        "title": "违反和解除劳动合同的经济补偿办法",
        "short_title": "违反和解除劳动合同的经济补偿办法",
        "caption": "（1994年12月3日劳部发〔1994〕481号公布　自1995年1月1日起施行）",
        "url": "https://hrss.shandong.gov.cn/articles/ch06547/202012/d89dbdff-556f-4945-a83d-a3cfd0e6861b.shtml",
        "source_name": "山东省人力资源和社会保障厅（转劳动部文件）",
        "issuer": "劳动部",
        "doc_number": "劳部发〔1994〕481号",
        "promulgated": "1994-12-03",
        "effective": "1995-01-01",
        "status": "已废止",
        "notes": "部门规范性文件（劳部发，非部令规章），按部门规章层级收录。已废止：2017年11月人力资源社会保障部文件清理中宣布废止。",
    },
    {
        "id": "mohrss-xj-1990-2",
        "raw_id": "xj-1990-2",
        "title": "女职工禁忌劳动范围的规定",
        "short_title": "女职工禁忌劳动范围的规定",
        "caption": "（1990年1月18日劳安字〔1990〕2号发布　自发布之日起施行）",
        "url": "https://rst.xinjiang.gov.cn/xjrst/c112752/201005/8721bcbe6fd1423a8921c753cda86267.shtml",
        "source_name": "新疆维吾尔自治区人力资源和社会保障厅（转劳动部文件）",
        "issuer": "劳动部",
        "doc_number": "劳安字〔1990〕2号",
        "promulgated": "1990-01-18",
        "effective": "1990-01-18",
        "status": "已废止",
        "notes": "已废止：根据2016年4月12日《人力资源社会保障部关于废止部分规章的决定》（人力资源社会保障部令第28号）废止。",
    },
    {
        "id": "mohrss-431593",
        "raw_id": "431593",
        "title": "关于《中外合资人才中介机构管理暂行规定》的补充规定",
        "short_title": "中外合资人才中介机构补充规定",
        "caption": "（2007年11月16日人事部令第8号公布　自2008年1月1日起施行）",
        "url": "https://www.mohrss.gov.cn/xxgk2020/gzk/gz/202112/t20211228_431593.html",
        "source_name": "中华人民共和国人力资源和社会保障部",
        "issuer": "人事部",
        "doc_number": "人事部令第8号",
        "promulgated": "2007-11-16",
        "effective": "2008-01-01",
        "status": "有效",
        "topics": ["就业促进", "涉外用工"],
        "allow_zero_articles": True,
        "notes": "以人事部令第8号（部门规章）形式发布，正文按“一、二、三”分项，无“第X条”条号，故条文数为0。",
    },
]

NORMATIVE_DIR = PROJECT / "data" / "normative-documents"

# 规范性文件（非规章，但劳动实务必引）。mohrss 官网规章库不收录，来源为部官网
# 法规司栏目 / 中国政府网 / 省级人社部门政府网站，均给出官方 https 页面。
NORMATIVE_DOCS: list[dict] = [
    {
        "id": "mohrss-norm-2005-12",
        "raw_id": "gd-2005-12",
        "title": "关于确立劳动关系有关事项的通知",
        "short_title": "确立劳动关系通知",
        "caption": "（劳社部发〔2005〕12号　2005年5月25日公布）",
        "issuer": "劳动和社会保障部",
        "doc_number": "劳社部发〔2005〕12号",
        "promulgated": "2005-05-25",
        "effective": "2005-05-25",
        "status": "有效",
        "url": "https://gdwsxf.gd.gov.cn/zcfg/content/mpost_2279696.html",
        "source_name": "广东省信访局（转劳动和社会保障部文件）",
        "topics": ["劳动合同", "就业促进"],
        "start": r"近一个时期",
        "notes": "部门规范性文件。认定事实劳动关系（含超龄劳动者、平台用工）最常引用的依据。",
    },
    {
        "id": "mohrss-norm-2008-3",
        "raw_id": "bj-2008-3",
        "title": "关于职工全年月平均工作时间和工资折算问题的通知",
        "short_title": "工时折算通知（2008）",
        "caption": "（劳社部发〔2008〕3号　2008年1月3日公布）",
        "issuer": "劳动和社会保障部",
        "doc_number": "劳社部发〔2008〕3号",
        "promulgated": "2008-01-03",
        "effective": "2008-01-03",
        "status": "已废止",
        "url": "https://rsj.beijing.gov.cn/xxgk/2024zcwj/202409/t20240906_3791491.html",
        "source_name": "北京市人力资源和社会保障局（转劳动和社会保障部文件）",
        "topics": ["劳动基准", "工资保障"],
        "start": r"根据《全国年节及纪念日放假办法》",
        "notes": "部门规范性文件。月计薪天数 21.75 天的出处。已废止：根据《人力资源社会保障部关于职工全年月平均工作时间和工资折算问题的通知》（人社部发〔2025〕2号）同时废止，现行折算规则见该通知（月计薪天数仍为21.75天）。",
    },
    {
        "id": "mohrss-norm-2025-2",
        "raw_id": "gov-6995777",
        "title": "人力资源社会保障部关于职工全年月平均工作时间和工资折算问题的通知",
        "short_title": "工时折算通知（2025）",
        "caption": "（人社部发〔2025〕2号　2025年1月1日公布）",
        "issuer": "人力资源和社会保障部",
        "doc_number": "人社部发〔2025〕2号",
        "promulgated": "2025-01-01",
        "effective": "2025-01-01",
        "status": "有效",
        "url": "https://www.gov.cn/zhengce/zhengceku/202501/content_6995777.htm",
        "source_name": "中国政府网（转人力资源社会保障部）",
        "topics": ["劳动基准", "工资保障"],
        "start": r"根据《国务院关于修改",
        "notes": "部门规范性文件。法定节假日增至13天后现行工时、工资折算规则；月计薪天数21.75天。",
    },
    {
        "id": "mohrss-norm-2021-56",
        "raw_id": "gov-5626761",
        "title": "关于维护新就业形态劳动者劳动保障权益的指导意见",
        "short_title": "新就业形态指导意见",
        "caption": "（人社部发〔2021〕56号　2021年7月16日公布）",
        "issuer": "人力资源和社会保障部、国家发展改革委、交通运输部、应急管理部、市场监管总局、国家医疗保障局、最高人民法院、全国总工会",
        "doc_number": "人社部发〔2021〕56号",
        "promulgated": "2021-07-16",
        "effective": "2021-07-16",
        "status": "有效",
        "url": "https://www.gov.cn/zhengce/zhengceku/2021-07/23/content_5626761.htm",
        "source_name": "中国政府网（转人力资源社会保障部）",
        "topics": ["新就业形态", "就业促进", "劳动保障监察"],
        "start": r"近年来，平台经济迅速发展",
        "notes": "部门规范性文件。平台用工（不完全符合确立劳动关系情形）的核心政策依据。",
    },
    {
        "id": "mohrss-norm-2003-12",
        "raw_id": "gov-62263",
        "title": "关于非全日制用工若干问题的意见",
        "short_title": "非全日制用工意见",
        "caption": "（劳社部发〔2003〕12号　2003年5月30日公布）",
        "issuer": "劳动和社会保障部",
        "doc_number": "劳社部发〔2003〕12号",
        "promulgated": "2003-05-30",
        "effective": "2003-05-30",
        "status": "有效",
        "url": "https://www.gov.cn/gongbao/content/2003/content_62263.htm",
        "source_name": "中国政府网（国务院公报）",
        "topics": ["劳动合同", "劳动基准", "就业促进"],
        "start": r"近年来，以小时工为主要形式",
        "notes": "部门规范性文件。非全日制用工口径；2008年《劳动合同法》施行后关于非全日制用工的规定与该法不一致的，以劳动合同法为准。",
    },
    {
        "id": "mohrss-norm-1995-309",
        "raw_id": "411025",
        "title": "关于贯彻执行《中华人民共和国劳动法》若干问题的意见",
        "short_title": "劳动法若干问题意见",
        "caption": "（劳部发〔1995〕309号　1995年8月4日公布）",
        "issuer": "劳动部",
        "doc_number": "劳部发〔1995〕309号",
        "promulgated": "1995-08-04",
        "effective": "1995-08-04",
        "status": "有效",
        "url": "https://www.mohrss.gov.cn/fgs/202103/t20210312_411025.html",
        "source_name": "中华人民共和国人力资源和社会保障部（法规司）",
        "topics": ["劳动合同", "劳动基准", "工资保障", "综合/其他"],
        "start": r"《中华人民共和国劳动法》（以下简称劳动法）已于",
        "notes": "部门规范性文件。共100条；部分内容已被《劳动合同法》《劳动合同法实施条例》等新法取代，适用时以新法为准。",
    },
    {
        "id": "moe-norm-2021-4",
        "raw_id": "gov-5669670",
        "title": "职业学校学生实习管理规定",
        "short_title": "职业学校学生实习管理规定",
        "caption": "（教职成〔2021〕4号　2021年12月31日印发）",
        "issuer": "教育部、工业和信息化部、财政部、人力资源和社会保障部、应急管理部、国务院国有资产监督管理委员会、国家市场监督管理总局、中国银行保险监督管理委员会",
        "doc_number": "教职成〔2021〕4号",
        "promulgated": "2021-12-31",
        "effective": "2021-12-31",
        "status": "有效",
        "url": "https://www.gov.cn/zhengce/zhengceku/2022-01/21/content_5669670.htm",
        "docx_url": "https://www.gov.cn/zhengce/zhengceku/2022-01/21/5669670/files/54d94cea8d484671b08cc7f16ef7db2a.docx",
        "source_name": "中国政府网（转教育部等八部门）",
        "topics": ["职业培训", "特殊群体保护", "劳动安全卫生"],
        "kind": "docx",
        "notes": "部门规范性文件（教育部等八部门）。规定实习生年龄（未满16周岁不得岗位实习）等，是实习生权益保护的直接依据。",
    },
    {
        "id": "mohrss-norm-1991-46",
        "raw_id": "431512",
        "title": "城镇集体所有制企业工资同经济效益挂钩办法",
        "short_title": "城镇集体企业工效挂钩办法",
        "caption": "（1990年10月5日劳薪字〔1991〕46号公布　自公布之日起施行）",
        "issuer": "劳动部",
        "doc_number": "劳薪字〔1991〕46号",
        "promulgated": "1990-10-05",
        "effective": "1990-10-05",
        "status": "有效",
        "url": "https://www.mohrss.gov.cn/xxgk2020/gzk/gz/202112/t20211228_431512.html",
        "source_name": "中华人民共和国人力资源和社会保障部",
        "topics": ["工资保障"],
        "start": r"根据国务院国发〔1990〕59号文件精神",
        "notes": "按“一、二、三”分项，无“第X条”条号，故条文数为0。部官网题注记为“1990年10月5日公布”，与发文字号劳薪字〔1991〕46号的年份不一致，此处照录原页面题注。",
    },
    {
        "id": "mohrss-norm-1994-50",
        "raw_id": "431563",
        "title": "机关、事业单位工人技术等级岗位考核暂行办法",
        "short_title": "工人技术等级岗位考核办法",
        "caption": "（1994年12月22日人薪发〔1994〕50号公布　自公布之日起施行）",
        "issuer": "人事部",
        "doc_number": "人薪发〔1994〕50号",
        "promulgated": "1994-12-22",
        "effective": "1994-12-22",
        "status": "有效",
        "url": "https://www.mohrss.gov.cn/xxgk2020/gzk/gz/202112/t20211228_431563.html",
        "source_name": "中华人民共和国人力资源和社会保障部",
        "topics": ["职业培训", "人事关系"],
        "start": r"根据《国务院关于机关和事业单位工作人员工资制度改革问题的通知",
        "notes": "按“一、二、三”分项，无“第X条”条号，故条文数为0。",
    },
    {
        "id": "mohrss-norm-1990-4",
        "raw_id": "431505",
        "title": "企事业单位评聘专业技术职务若干问题暂行规定",
        "short_title": "评聘专业技术职务暂行规定",
        "caption": "（1990年11月10日人职发〔1990〕4号公布　自公布之日起施行）",
        "issuer": "人事部",
        "doc_number": "人职发〔1990〕4号",
        "promulgated": "1990-11-10",
        "effective": "1990-11-10",
        "status": "有效",
        "url": "https://www.mohrss.gov.cn/xxgk2020/gzk/gz/202112/t20211228_431505.html",
        "source_name": "中华人民共和国人力资源和社会保障部",
        "topics": ["人事关系"],
        "start": r"目前，全国企事业单位首次专业技术职务评聘工作已经结束",
        "notes": "按“一、二、三”分项，无“第X条”条号，故条文数为0。",
    },
]

BLOCK_TAGS = {
    "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "ul", "ol", "section", "article", "dd", "dt", "dl", "center",
    "hr", "blockquote", "pre", "tfoot", "thead", "tbody", "td", "th",
}
SKIP_TAGS = {"script", "style", "noscript"}

CH_CHAPTER = re.compile(r"^第[一二三四五六七八九十百零〇两]+编")
CH_CHAPTER2 = re.compile(r"^第[一二三四五六七八九十百零〇两]+章")
CH_SECTION = re.compile(r"^第[一二三四五六七八九十百零〇两]+节")
CH_ARTICLE = re.compile(r"^第[一二三四五六七八九十百零〇两]+条(?=[\s　]|$)")
ARTICLE_SPLIT = re.compile(r"(?=第[一二三四五六七八九十百零〇两]+条[\s　])")

ATTACH_FILE_RE = re.compile(r"\.(?:docx?|pdf|xlsx?|wps|zip|rar)\s*$", re.I)

NOISE_RE = re.compile(
    r"^(责任编辑|分享到|【打印】|【关闭|关闭窗口|扫一扫|相关链接|相关新闻|附件下载|"
    r"上一篇|下一篇|字号|浏览次数|网站地图|主办单位|版权所有|返回顶部|打印本页)"
)


# --------------------------------------------------------------------------- http
class Fetcher:
    """限速 + 重试的极简 HTML 抓取器。"""

    def __init__(self, min_interval: float = 0.55, timeout: int = 45, verbose: bool = False):
        self.min_interval = min_interval
        self.timeout = timeout
        self.verbose = verbose
        self._last = 0.0
        self.requests = 0

    def get(self, url: str, tries: int = 5) -> bytes:
        last: Exception | None = None
        for attempt in range(tries):
            wait = self.min_interval + random.uniform(0, 0.35) - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    blob = resp.read()
                self.requests += 1
                if len(blob) < 512:
                    raise RuntimeError(f"suspiciously small response ({len(blob)} bytes)")
                return blob
            except Exception as exc:  # noqa: BLE001 - any transport error is retryable
                last = exc
                if self.verbose:
                    print(f"  ! retry {attempt + 1}/{tries} {url}: {exc}", file=sys.stderr)
                time.sleep(min(20, 1.5 * (attempt + 1)) + random.uniform(0, 0.8))
        raise RuntimeError(f"request failed after {tries} tries: {url}: {last}")


# --------------------------------------------------------------------------- html
def plain(fragment: str) -> str:
    """去标签、反转义、压缩空白。"""
    fragment = re.sub(r"<[^>]+>", " ", fragment or "")
    fragment = html.unescape(fragment)
    return re.sub(r"\s+", " ", fragment.replace("\xa0", " ")).strip()


class ContainerText(HTMLParser):
    """抽取第一个命中容器的内部文本（按块级标签断行，行内标签拼接）。

    gz 详情页正文在 <div class="gz_content_txt">，政策法规库详情页在
    <div class="art_p">；中国政府网在 id="UCAP-CONTENT"；省级站点分别是
    <div class="show"> / <div class="article-detail">。
    """

    def __init__(self, id_names: tuple[str, ...] = (), class_names: tuple[str, ...] = ()):
        super().__init__(convert_charrefs=True)
        self.id_names = id_names
        self.class_names = class_names
        self.started = False
        self.done = False
        self.container = ""
        self.nest = 0
        self.skip = 0
        self.buf: list[str] = []
        self.lines: list[str] = []

    def _is_target(self, tag: str, attrs: dict) -> bool:
        if attrs.get("id") in self.id_names:
            return True
        classes = (attrs.get("class") or "").split()
        return any(c in self.class_names for c in classes)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.started:
            if self._is_target(tag, attrs):
                self.started = True
                self.container = tag
                self.nest = 0
            return
        if tag in SKIP_TAGS:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == self.container:
            self.nest += 1
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr") and self.started and not self.skip:
            self._flush()

    def handle_endtag(self, tag):
        if not self.started:
            return
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == self.container:
            if self.nest > 0:
                self.nest -= 1
            else:
                self._flush()
                self.started = False
                self.done = True
            return
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self.started and not self.skip:
            self.buf.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf).replace("\xa0", " ")).strip()
        self.buf = []
        if text:
            self.lines.append(text)

    def close(self) -> list[str]:
        super().close()
        self._flush()
        return self.lines


def extract_lines(raw: bytes, *, page: str = "") -> list[str]:
    """按不同来源选择正文容器，返回清洗后的行列表。"""
    text = raw.decode("utf-8", errors="replace")
    candidates = [
        (("UCAP-CONTENT",), ()),
        ((), ("gz_content_txt",)),
        ((), ("art_p",)),
        ((), ("article-detail",)),
        ((), ("article_content", "xl-zw-info")),
        (("zw",), ()),
        (("insMainConTxt",), ()),
        ((), ("TRS_Editor", "TRS_UEDITOR")),
        ((), ("show",)),
    ]
    if page == "gov":
        candidates = [(("UCAP-CONTENT",), ())] + candidates
    for ids, classes in candidates:
        parser = ContainerText(ids, classes)
        try:
            parser.feed(text)
            parser.close()
        except Exception:  # noqa: BLE001 - malformed markup: try next container
            continue
        if parser.lines:
            return parser.lines
    return []


def merge_char_lines(lines: list[str]) -> list[str]:
    """部分页面把正文逐字排成独立块（每个字一行），按条/章边界重新合并。"""
    if len(lines) < 20:
        return lines
    short = sum(1 for ln in lines if len(ln) <= 2)
    if short / len(lines) < 0.5:
        return lines
    joined = "".join(lines)
    joined = re.sub(r"(第[一二三四五六七八九十百零〇两]+[编章节])", r"\n\1", joined)
    joined = re.sub(r"(?=第[一二三四五六七八九十百零〇两]+条[\s　])", "\n", joined)
    return [ln.strip() for ln in joined.split("\n") if ln.strip()]


# --------------------------------------------------------------------------- catalog
def parse_gz_list(page_html: str) -> list[dict]:
    out = []
    for block in re.findall(r'<div class="title">(.*?)</div>', page_html, re.S):
        anchor = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not anchor:
            continue
        caption = re.search(r"<p>(.*?)</p>", block, re.S)
        out.append(
            {
                "href": anchor.group(1),
                "title": plain(anchor.group(2)),
                "caption": plain(caption.group(1)) if caption else "",
                "list": "gz",
                "path": LIST_GZ + "/" + anchor.group(1).lstrip("./"),
            }
        )
    return out


def parse_bmgz_list(page_html: str) -> list[dict]:
    out = []
    chunks = re.findall(
        r'<li class="tem_li".*?(?=<li class="tem_li"|</ul>)', page_html, re.S
    )
    for block in chunks:
        anchor = re.search(
            r'<div class="res_title[^"]*">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S
        )
        if not anchor:
            continue

        def meta(name: str) -> str:
            hit = re.search(r"<!--" + name + r"(?:-->|开始-->)(.*?)<!--", block, re.S)
            return plain(hit.group(1)) if hit else ""

        out.append(
            {
                "href": anchor.group(1),
                "title": plain(anchor.group(2)),
                "caption": "",
                "list": "bmgz",
                "path": LIST_BMGZ + "/" + anchor.group(1).lstrip("./"),
                "index_no": meta("索引号"),
                "category": meta("分类"),
                "issuer_raw": meta("发布单位"),
                "promulgated_raw": meta("发文日期"),
                "doc_number": meta("发文字号"),
            }
        )
    return out


def crawl_catalog(fetcher: Fetcher) -> dict[str, dict]:
    """抓列表页，返回 title -> 详情页信息（优先“规章”列表里的版本）。"""
    catalog: dict[str, dict] = {}
    for prefix, parser in ((LIST_GZ, parse_gz_list), (LIST_BMGZ, parse_bmgz_list)):
        first = fetcher.get(MIRROR + prefix + "/index.html").decode("utf-8", "replace")
        page_count = int((re.search(r"countPage\s*=\s*(\d+)", first) or [0, "1"])[1])
        entries = parser(first)
        for page in range(1, page_count):
            listing = fetcher.get(MIRROR + f"{prefix}/index_{page}.html").decode("utf-8", "replace")
            entries.extend(parser(listing))
        print(f"  {prefix}: {page_count} 页 / {len(entries)} 条", file=sys.stderr)
        for entry in entries:
            old = catalog.get(entry["title"])
            # gz（现行规章库）优先；bmgz 仅补充 gz 没有的条目
            if old is None or (old["list"] == "bmgz" and entry["list"] == "gz"):
                catalog[entry["title"]] = entry
    return catalog


# --------------------------------------------------------------------------- detail
def extract_detail_title(raw: bytes) -> str:
    """详情页 <h1>（规章库）/ <div class="artT">（政策法规库）里的标题。"""
    text = raw.decode("utf-8", "replace")
    for pattern in (r"<h1[^>]*>(.*?)</h1>", r'<div class="artT">(.*?)</div>'):
        hit = re.search(pattern, text, re.S)
        if hit:
            return plain(hit.group(1))
    return ""


def extract_detail_caption(raw: bytes) -> str:
    """规章库详情页把题注放在 <h3>，政策法规库放在正文首段（由调用方兜底）。"""
    text = raw.decode("utf-8", "replace")
    hit = re.search(r"<h3[^>]*>(.*?)</h3>", text, re.S)
    return plain(hit.group(1)) if hit else ""


def split_title_caption(lines: list[str], title: str) -> tuple[str, list[str]]:
    """从详情页正文中提取题注（通过/公布/施行日期那段括号说明）。"""
    caption = ""
    for line in lines[:6]:
        if line.startswith("（") and re.search(r"(公布|发布|通过|修订|修正)", line):
            caption = line
            break
    return caption, lines


def find_body_start(lines: list[str], title: str) -> int:
    """返回正文起始下标：从“第一条”所在位置开始（保留其前面的章标题/题注）。"""
    first_article = None
    for idx, line in enumerate(lines):
        if CH_ARTICLE.match(line):
            first_article = idx
            break
    if first_article is None:
        return 0
    start = first_article
    while start > 0:
        prev = lines[start - 1]
        if CH_CHAPTER.match(prev) or CH_CHAPTER2.match(prev) or CH_SECTION.match(prev):
            start -= 1
        elif prev.startswith("（") and re.search(r"(公布|发布|通过|修订|修正)", prev):
            start -= 1
        else:
            break
    return start


def normalize_blocks(lines: list[str], title: str) -> tuple[str, list[tuple[str, str]]]:
    """清洗并切分成 (kind, text) 块；kind ∈ chapter/section/text。"""
    lines = merge_char_lines(lines)
    start = find_body_start(lines, title)
    blocks: list[tuple[str, str]] = []
    for line in lines[start:]:
        if NOISE_RE.match(line):
            break
        if ATTACH_FILE_RE.search(line):
            # 附件下载链接的文字不是正文
            continue
        # 一行里挤了两条以上的，按“第X条”切开
        parts = [p.strip() for p in ARTICLE_SPLIT.split(line) if p.strip()]
        for part in parts:
            if CH_CHAPTER2.match(part) or CH_CHAPTER.match(part):
                blocks.append(("chapter", part))
            elif CH_SECTION.match(part):
                blocks.append(("section", part))
            else:
                blocks.append(("text", part))
    # 去掉尾部噪声块 / 悬空的“附件：”
    while blocks and blocks[-1][0] == "text" and (
        NOISE_RE.match(blocks[-1][1]) or re.fullmatch(r"附\s*件\s*[:：]?", blocks[-1][1])
    ):
        blocks.pop()
    return "", blocks


def count_articles(blocks: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """返回 (正文条号列表, 附件/附录中引用的条号列表)。"""
    numbers: list[str] = []
    attach: list[str] = []
    in_attach = False
    for _, text in blocks:
        if not in_attach and re.match(r"^(附件|附录)", text):
            in_attach = True
        match = CH_ARTICLE.match(text)
        if match:
            (attach if in_attach else numbers).append(match.group(0)[1:-1])
    return numbers, attach


def build_markdown(title: str, caption: str, blocks: list[tuple[str, str]]) -> str:
    out = [f"# {title}", ""]
    if caption:
        out += [caption, ""]
    for kind, text in blocks:
        if kind == "chapter":
            out += [f"## {text}", ""]
        elif kind == "section":
            out += [f"### {text}", ""]
        else:
            out += [text, ""]
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- metadata
CN_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
DATE_SPAN = re.compile(r"自(\d{4})年(\d{1,2})月(\d{1,2})日起施行")
DOC_NUMBER = re.compile(
    r"((?:[\u4e00-\u9fa5A-Za-z]+、)*[\u4e00-\u9fa5A-Za-z]+"
    r"(?:令第\d+号|[〔﹝［\[]\d{4}[〕﹞］\]]\d+号))"
)
# 文号简称 / 旧称 → SCHEMA 里的规范机关名
ISSUER_MAP = {
    "劳部发": "劳动部",
    "劳安字": "劳动部",
    "劳社部发": "劳动和社会保障部",
    "劳社厅发": "劳动和社会保障部办公厅",
    "劳社部函": "劳动和社会保障部",
    "劳动保障部": "劳动和社会保障部",
    "劳动部": "劳动部",
    "人社部": "人力资源和社会保障部",
    "人力资源社会保障部": "人力资源和社会保障部",
    "人事部": "人事部",
    "人职发": "人事部",
    "人薪发": "人事部",
    "人专发": "人事部",
    "人发": "人事部",
    "劳人培": "劳动人事部",
    "劳人薪": "劳动人事部",
    "劳人编": "劳动人事部",
    "国家卫生计生委": "国家卫生和计划生育委员会",
    "国家卫生健康委": "国家卫生健康委员会",
    "国家医保局": "国家医疗保障局",
    "银监会": "中国银行业监督管理委员会",
    "证监会": "中国证券监督管理委员会",
    "保监会": "中国保险监督管理委员会",
}


def iso(y: str, m: str, d: str) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def parse_meta_from_caption(caption: str) -> dict:
    meta: dict = {}
    dates = CN_DATE.findall(caption)
    if dates:
        meta["promulgated"] = iso(*dates[0])
    span = DATE_SPAN.search(caption)
    if span:
        meta["effective"] = iso(*span.groups())
    elif dates:
        meta["effective"] = meta.get("promulgated", iso(*dates[0]))
    # 文号前常紧贴日期（“1994年12月6日劳部发〔1994〕489号”），先去掉日期再匹配
    probe = CN_DATE.sub("", caption).replace("（", " ").replace("(", " ")
    number = DOC_NUMBER.search(probe)
    if number:
        meta["doc_number"] = number.group(1)
    # 修订沿革：题注“公布/发布”之后、含“修订/修正/修改”的那段
    for sep in ("公布", "发布"):
        if sep in caption:
            tail = caption.split(sep, 1)[1].strip(" 　（）()")
            tail = re.sub(r"^自.{0,24}?施行\s*", "", tail).strip()
            if tail and re.search(r"修订|修正|修改", tail):
                meta["version_note"] = re.sub(r"\s+", " ", tail)
            break
    return meta


def issuer_from_doc_number(doc_number: str) -> str:
    """从“劳动保障部令第8号 / 人社部发〔2021〕1号 / 甲部、乙委令第3号”推出发布机关。"""
    if not doc_number:
        return ""
    head = re.split(r"(?:令第|[〔﹝［\[])", doc_number)[0].strip()
    if not head:
        return ""
    parts = [p for p in head.split("、") if p]
    resolved = []
    for part in parts:
        name = ISSUER_MAP.get(part)
        if name is None:
            for key, val in sorted(ISSUER_MAP.items(), key=lambda kv: -len(kv[0])):
                if part.startswith(key):
                    name = val + part[len(key):]
                    break
        resolved.append(name or part)
    return "、".join(resolved)


def pick_topics(title: str, notes: str = "") -> list[str]:
    haystack = title + " " + notes
    topics: list[str] = []
    for name, pattern in TOPIC_RULES:
        if name in topics:
            continue
        if re.search(pattern, haystack):
            topics.append(name)
        if len(topics) >= 4:
            break
    return topics or [TOPIC_FALLBACK]


def yq(value: str) -> str:
    """JSON 字符串即合法的 YAML 双引号标量。"""
    return json.dumps(value, ensure_ascii=False)


def front_matter(entry: dict, body: str, articles: int) -> str:
    lines = ["---"]
    fields = [
        ("id", entry["id"]),
        ("title", entry["title"]),
        ("short_title", entry["short_title"]),
        ("level", entry.get("level", "部门规章")),
        ("level_code", entry.get("level_code", "4")),
        ("issuer", entry["issuer"]),
        ("doc_number", entry["doc_number"]),
        ("promulgated", entry["promulgated"]),
        ("effective", entry["effective"]),
        ("status", entry["status"]),
        ("status_code", str(STATUS_CODE[entry["status"]])),
        ("category", entry.get("category", "部门规章")),
        ("doc_type", entry.get("doc_type", "部门规章")),
        ("province", ""),
        ("topics", json.dumps(entry["topics"], ensure_ascii=False)),
        ("source", entry["source"]),
        ("source_name", entry["source_name"]),
        ("retrieved", RETRIEVED),
        ("sha256", ""),
        ("chars", str(len(body.strip()))),
        ("articles", str(articles)),
        ("version_group", entry["title"]),
        ("version_note", entry.get("version_note", "")),
        ("notes", entry.get("notes", "")),
    ]
    for key, value in fields:
        if key in ("level_code", "status_code", "retrieved", "promulgated", "effective", "articles", "chars"):
            lines.append(f"{key}: {value}")
        elif key in ("topics", "related"):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {yq(value)}")
    lines.append("related: []")
    lines.append("---")
    return "\n".join(lines)


# ------------------------------------------------------------------- normative
def pandoc_docx_markdown(data: bytes) -> str:
    """用 pandoc 把官方 .docx 附件转成 markdown（仅指向政府网附件时使用）。"""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        proc = subprocess.run(
            ["pandoc", path, "-t", "gfm", "--wrap=none"],
            check=True, capture_output=True, text=True,
        )
        return proc.stdout
    finally:
        Path(path).unlink(missing_ok=True)


def docx_lines(data: bytes, title: str) -> list[str]:
    lines: list[str] = []
    for raw in pandoc_docx_markdown(data).split("\n"):
        line = raw.strip().replace("**", "")
        if not line:
            continue
        if set(line) <= set("# "):
            continue
        lines.append(line.lstrip("# ").strip())
    if lines and lines[0] == title:
        lines.pop(0)
    return [ln for ln in lines if ln]


def lines_to_blocks(lines: list[str]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for line in lines:
        if NOISE_RE.match(line):
            break
        if ATTACH_FILE_RE.search(line):
            continue
        if CH_CHAPTER2.match(line) or CH_CHAPTER.match(line):
            blocks.append(("chapter", line))
        elif CH_SECTION.match(line):
            blocks.append(("section", line))
        else:
            blocks.append(("text", line))
    while blocks and blocks[-1][0] == "text" and NOISE_RE.match(blocks[-1][1]):
        blocks.pop()
    return blocks


def process_normative(fetcher: Fetcher, doc: dict, *, force: bool, write: bool = True) -> dict:
    if write:
        NORMATIVE_DIR.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{doc['raw_id']}.html"

    if doc.get("kind") == "docx":
        if raw_path.exists() and raw_path.stat().st_size > 2000 and not force:
            data = raw_path.read_bytes()
        else:
            data = fetcher.get(doc["docx_url"])
            if write:
                raw_path.write_bytes(data)
        lines = docx_lines(data, doc["title"])
    else:
        if raw_path.exists() and raw_path.stat().st_size > 2000 and not force:
            raw = raw_path.read_bytes()
        else:
            # 人社部官网正文被 WAF 拦截，统一走镜像同一路径抓取
            fetch_url = doc["url"]
            if "mohrss.gov.cn" in fetch_url:
                fetch_url = MIRROR + "/" + urllib.parse.urlsplit(fetch_url).path.lstrip("/")
            raw = fetcher.get(fetch_url)
            if write:
                raw_path.write_bytes(raw)
        lines = extract_lines(raw, page="gov")
        marker = re.compile(doc["start"]) if doc.get("start") else None
        if marker is not None:
            for idx, line in enumerate(lines):
                if marker.search(line):
                    lines = lines[idx:]
                    break
            else:
                raise RuntimeError(f"正文起点未找到: {doc['title']}")
    blocks = lines_to_blocks(lines)
    if not blocks:
        raise RuntimeError(f"正文为空: {doc['title']}")
    numbers = [CH_ARTICLE.match(text).group(0)[1:-1] for _, text in blocks if CH_ARTICLE.match(text)]
    body = build_markdown(doc["title"], doc["caption"], blocks)

    entry = {
        "id": doc["id"],
        "title": doc["title"],
        "short_title": doc.get("short_title") or doc["title"],
        "level": "规范性文件",
        "level_code": "7",
        "doc_type": "规范性文件",
        "category": "规范性文件",
        "issuer": doc["issuer"],
        "doc_number": doc["doc_number"],
        "promulgated": doc["promulgated"],
        "effective": doc["effective"],
        "status": doc["status"],
        "topics": doc["topics"],
        "version_note": doc.get("version_note", ""),
        "notes": doc["notes"],
        "source": doc["url"],
        "source_name": doc["source_name"],
    }
    md = front_matter(entry, body, len(numbers)) + "\n" + body
    md_path = NORMATIVE_DIR / safe_filename(doc["title"], doc["promulgated"][:4])
    if write:
        if force or not md_path.exists():
            md_path.write_text(md, encoding="utf-8")
        digest = hashlib.sha256(md_path.read_bytes()).hexdigest()
    else:
        digest = hashlib.sha256(md.encode("utf-8")).hexdigest()
    return {
        "id": doc["id"],
        "title": doc["title"],
        "doc_number": doc["doc_number"],
        "promulgated": doc["promulgated"],
        "effective": doc["effective"],
        "status": doc["status"],
        "source": doc["url"],
        "local_path": str(md_path.relative_to(PROJECT)),
        "raw_path": str(raw_path.relative_to(PROJECT)),
        "sha256": digest,
        "articles": len(numbers),
        "chars": len(body.strip()),
        "topics": doc["topics"],
        "issuer": doc["issuer"],
        "notes": doc["notes"],
        "level": "规范性文件",
    }


# --------------------------------------------------------------------------- main
def safe_filename(title: str, year: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "－", title).strip()
    return f"{name}-{year}.md"


def resolve_metadata(job: dict, raw: bytes, lines: list[str]) -> tuple[str, dict]:
    """汇总题注/列表页/人工核定三处元数据。"""
    title = job.get("title") or extract_detail_title(raw)
    caption = job.get("caption") or extract_detail_caption(raw)
    if not caption:
        caption, _ = split_title_caption(lines, title)
    meta: dict = parse_meta_from_caption(caption) if caption else {}

    # 人工核定值（补充文件）优先
    for key in (
        "issuer", "doc_number", "promulgated", "effective", "status",
        "version_note", "notes", "topics",
    ):
        if job.get(key):
            meta[key] = job[key]

    # 列表页兜底
    if not meta.get("promulgated") and job.get("promulgated_raw"):
        dates = CN_DATE.findall(job["promulgated_raw"])
        if dates:
            meta["promulgated"] = iso(*dates[0])
    if not meta.get("doc_number") and job.get("doc_number"):
        meta["doc_number"] = job["doc_number"]
    if not meta.get("issuer"):
        issuer = issuer_from_doc_number(meta.get("doc_number", ""))
        if not issuer and caption:
            probe = CN_DATE.sub("", caption).strip(" 　（）()")
            hit = re.match(r"([\u4e00-\u9fa5、]{2,20}?)(?:发布|公布)", probe)
            if hit:
                issuer = issuer_from_doc_number(hit.group(1) + "令第0号") or hit.group(1)
        meta["issuer"] = issuer or "人力资源和社会保障部"
    if not meta.get("promulgated"):
        raise RuntimeError(f"公布日期缺失: {title}")
    meta.setdefault("effective", meta["promulgated"])
    meta.setdefault("status", "有效")
    if meta["status"] not in STATUS_CODE:
        raise RuntimeError(f"非法状态 {meta['status']}: {title}")
    meta.setdefault("version_note", "")
    meta.setdefault("notes", "")
    meta["topics"] = meta.get("topics") or pick_topics(title, meta.get("notes", ""))
    meta["title"] = title
    meta["caption"] = caption
    return title, meta


def process_document(
    fetcher: Fetcher, job: dict, raw: bytes | None, *, force: bool, write: bool = True
) -> dict:
    if raw is None:
        raw = fetcher.get(job["fetch_url"])
    raw_path = RAW_DIR / f"{job['raw_id']}.html"
    if write:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        if force or not raw_path.exists():
            raw_path.write_bytes(raw)

    lines = extract_lines(raw, page=job.get("page_kind", ""))
    if not lines:
        raise RuntimeError(f"正文容器为空: {job['title']}")
    title, meta = resolve_metadata(job, raw, lines)
    _, blocks = normalize_blocks(lines, title)

    # 正文里重复出现的标题、题注（政策法规库/政府网页面会带）只保留一份
    while blocks and blocks[0][0] == "text" and blocks[0][1].strip() == title:
        blocks.pop(0)
    while blocks and blocks[0][0] == "text" and meta["caption"] and blocks[0][1] == meta["caption"]:
        blocks.pop(0)
    numbers, attach_numbers = count_articles(blocks)
    articles = len(numbers)
    if not blocks or (articles == 0 and not job.get("allow_zero_articles")):
        raise RuntimeError(f"未解析到条文: {title}")
    body = build_markdown(title, meta["caption"], blocks)

    entry = dict(job)
    entry.update(meta)
    entry["short_title"] = job.get("short_title") or title
    md = front_matter(entry, body, articles) + "\n" + body

    md_path = DATA_DIR / safe_filename(title, meta["promulgated"][:4])
    if write:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if force or not md_path.exists():
            md_path.write_text(md, encoding="utf-8")
        digest = hashlib.sha256(md_path.read_bytes()).hexdigest()
    else:
        digest = hashlib.sha256(md.encode("utf-8")).hexdigest()
    return {
        "id": entry["id"],
        "title": title,
        "doc_number": meta.get("doc_number", ""),
        "promulgated": meta["promulgated"],
        "effective": meta["effective"],
        "status": meta["status"],
        "source": entry["source"],
        "local_path": str(md_path.relative_to(PROJECT)),
        "raw_path": str(raw_path.relative_to(PROJECT)),
        "sha256": digest,
        "articles": articles,
        "chars": len(body.strip()),
        "topics": meta["topics"],
        "issuer": meta["issuer"],
        "version_note": meta["version_note"],
        "notes": meta["notes"],
        "list_source": entry.get("list_source", "supplement"),
        "_numbers": numbers,
        "_attach_numbers": attach_numbers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取人社部部门规章")
    parser.add_argument("--force", action="store_true", help="覆盖已有 md / raw")
    parser.add_argument("--only", nargs="*", default=None, help="只处理指定标题（可多个）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 篇（调试用）")
    parser.add_argument("--dry-run", action="store_true", help="不写文件，只打印解析报告")
    parser.add_argument("--skip-normative", action="store_true", help="不处理规范性文件（data/normative-documents）")
    parser.add_argument("--min-interval", type=float, default=0.55, help="请求最小间隔秒数")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not 0.5 <= args.min_interval <= 1.0:
        parser.error("--min-interval 应在 0.5–1.0 之间（礼貌抓取）")

    fetcher = Fetcher(min_interval=args.min_interval, verbose=args.verbose)
    print("抓取列表页 …", file=sys.stderr)
    catalog = crawl_catalog(fetcher)

    wanted = set(args.only) if args.only else None
    jobs: list[dict] = []
    for title, entry in catalog.items():
        if DECISION_RE.search(title) or title in EXCLUDE_TITLES:
            continue
        if wanted and title not in wanted:
            continue
        path = entry["path"]
        page_id = re.search(r"_(\d+)\.html$", path).group(1)
        jobs.append(
            {
                "id": "mohrss-" + page_id,
                "raw_id": page_id,
                "title": title,
                "caption": entry.get("caption", ""),
                "doc_number": entry.get("doc_number", ""),
                "promulgated_raw": entry.get("promulgated_raw", ""),
                "fetch_url": MIRROR + path,
                "source": CANONICAL + path,
                "source_name": "中华人民共和国人力资源和社会保障部",
                "page_kind": "mohrss",
                "list_source": entry["list"],
            }
        )
    for special in SPECIALS:
        if wanted and special["title"] not in wanted:
            continue
        job = dict(special)
        job["fetch_url"] = special["url"]
        job["source"] = special["url"]
        job["page_kind"] = "gov"
        jobs.append(job)
    if args.limit:
        jobs = jobs[: args.limit]
    normative_jobs: list[dict] = []
    if not args.skip_normative:
        normative_jobs = [d for d in NORMATIVE_DOCS if not wanted or d["title"] in wanted]
    if not jobs and not normative_jobs:
        print("没有待处理条目", file=sys.stderr)
        return 1

    print(f"待处理 {len(jobs)} 篇（列表超集 {len(catalog)} 条）", file=sys.stderr)
    items: list[dict] = []
    failures: list[dict] = []
    for i, job in enumerate(jobs, 1):
        try:
            raw = None
            raw_path = RAW_DIR / f"{job['raw_id']}.html"
            if raw_path.exists() and raw_path.stat().st_size > 2000 and not args.force:
                raw = raw_path.read_bytes()
            item = process_document(
                fetcher, job, raw, force=args.force, write=not args.dry_run
            )
            items.append(item)
            print(
                f"[{i}/{len(jobs)}] OK  {item['articles']:>3}条 {item['chars']:>6}字 "
                f"{item['status']} {item['title']}",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001 - 单篇失败不中断
            failures.append({"title": job.get("title"), "url": job.get("fetch_url"), "error": str(exc)})
            print(f"[{i}/{len(jobs)}] FAIL {job.get('title')}: {exc}", file=sys.stderr)

    normative_items: list[dict] = []
    for i, doc in enumerate(normative_jobs, 1):
        try:
            item = process_normative(
                fetcher, doc, force=args.force, write=not args.dry_run
            )
            normative_items.append(item)
            print(
                f"[规范 {i}/{len(normative_jobs)}] OK {item['articles']:>3}条 "
                f"{item['chars']:>6}字 {item['title']}",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"title": doc.get("title"), "url": doc.get("url"), "error": str(exc)})
            print(f"[规范 {i}/{len(normative_jobs)}] FAIL {doc.get('title')}: {exc}", file=sys.stderr)

    # 条号连续性检查（附件里引用的其他法条单列，不参与判重）
    warnings = []
    for item in items:
        nums = item.pop("_numbers")
        item.pop("_attach_numbers", None)
        if nums and nums[0] != "一":
            warnings.append(f"{item['title']}: 首条为第{nums[0]}条")
        if len(set(nums)) != len(nums):
            warnings.append(f"{item['title']}: 正文条号重复")

    if args.dry_run:
        for item in items + normative_items:
            print(json.dumps({k: item[k] for k in ("title", "articles", "chars", "status", "topics")}, ensure_ascii=False))
        for warning in warnings:
            print(f"  WARN {warning}", file=sys.stderr)
        print(f"\n解析成功 {len(items)}，失败 {len(failures)}，告警 {len(warnings)}", file=sys.stderr)
        return 0

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    items.sort(key=lambda x: (x["promulgated"], x["title"]))
    index = {
        "source": "中华人民共和国人力资源和社会保障部（镜像 114.255.111.133）",
        "retrieved": RETRIEVED,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "script": "scripts/fetch_mohrss.py",
        "count": len(items),
        "items": items,
        "normative_count": len(normative_items),
        "normative_documents": normative_items,
        "failures": failures,
        "warnings": warnings,
    }
    (RESEARCH_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"\n写入 {len(items)} 篇部门规章 + {len(normative_items)} 篇规范性文件；"
        f"失败 {len(failures)}；告警 {len(warnings)}；HTTP 请求 {fetcher.requests} 次",
        file=sys.stderr,
    )
    if failures:
        for failure in failures:
            print(f"  FAIL {failure['title']}: {failure['error']}", file=sys.stderr)
    if warnings:
        for warning in warnings:
            print(f"  WARN {warning}", file=sys.stderr)
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
