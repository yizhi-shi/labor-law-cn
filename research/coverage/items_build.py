#!/usr/bin/env python3
"""构造劳动法领域国家级清单数据集（研究产物，不写入 data/）。

元数据优先取 flk 列表缓存；flk 未收录的层级（部门规章、两部由全国人大
批准的行政法规本体）以人工条目补齐，并在 note 中标注来源与核验状态。
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"

SXX = {1: "已废止", 2: "已修改", 3: "有效", 4: "尚未生效"}

# bbbs -> 施行日期补正（flk 列表 sxrq 为空时，按官方公布信息补，并在 note 说明）
EFFECTIVE_FIX = {
    "ff8080816f3cbb3c016f40927caf049c": ("2008-09-18", "flk sxrq 为空；国务院令第535号自公布之日施行"),
    "ff8080816f3cbb3c016f41114fec14e9": ("2004-12-01", "flk sxrq 为空；国务院令第423号 2004-12-01 施行"),
    "ff8080816f3cbb3c016f40f8971f0ef3": ("1999-01-22", "flk sxrq 为空；国务院令第258号自公布之日施行"),
    "ff8080816f3cbb3c016f40f97d360f29": ("1999-01-22", "flk sxrq 为空；国务院令第259号自公布之日施行"),
    "ff8080816f3e98bd016f420b9b460371": ("2008-01-01", "flk sxrq 为空；国务院令第514号 2008-01-01 施行"),
    "ff8080816f3cbb3c016f410f1ed51451": ("2012-04-28", "flk sxrq 为空；国务院令第619号自公布之日施行"),
    "ff8080816f3cbb3c016f40a1b7230583": ("2002-12-01", "flk sxrq 为空；国务院令第364号 2002-12-01 施行"),
    "ff8080816f3e9784016f423752750349": ("1996-10-30", "flk sxrq 为空；自公布之日施行"),
    "ff8080816f3cbb3c016f40ee9ee50c0f": ("2004-01-13", "flk 记录为 2014 修订版公布日 2014-07-29；原条例 2004-01-13 施行，修订未改施行日"),
    "ff8080816f3cbb3c016f40ea51880ae9": ("2004-02-01", "flk sxrq 为空；国务院令第393号 2004-02-01 施行"),
    "ff8080816f3cbb3c016f4087cdcc03d9": ("2011-12-01", "flk 记录为 2013 修订版公布日；2011 修订版 2011-12-01 施行"),
    "ff8080816f3cbb3c016f40d306b705f3": ("2003-06-01", "flk 记录为 2009 修订版公布日；原条例 2003-06-01 施行"),
    "ff8080816f3e9784016f4201bf5d028c": ("1990-01-01", "国务院批准、国家统计局 1990-01-01 发布施行"),
    "ff8080816f3cbb3c016f41260ca619e7": ("1995-05-01", "flk 记录为 1995-03-25 修订公布日；1995-05-01 施行"),
    "ff8080816f3e9784016f424fe00c04e5": ("1990-11-22", "flk sxrq 为空；自公布之日施行"),
    "ff8080816f3cbb3c016f40fd4631102f": ("1993-04-20", "flk sxrq 为空；国务院令第111号自公布之日施行"),
    "ff8080816f3e98bd016f41eb2b4a01cc": ("2007-05-01", "flk sxrq 为空；国务院令第488号 2007-05-01 施行"),
    "ff8080816f3cbb3c016f414082e71ee1": ("2018-10-01", "flk sxrq 为空；国务院令第700号 2018-10-01 施行"),
    "ff8080816f3cbb3c016f412e35e31b74": ("2016-05-01", "flk sxrq 为空；国务院令第667号 2016-05-01 施行"),
    "ff8080816f3cbb3c016f4125dd7719de": ("2014-07-01", "flk sxrq 为空；国务院令第652号 2014-07-01 施行"),
    "ff8080816f3cbb3c016f4143a1591f56": ("2019-04-01", "flk sxrq 为空；国务院令第708号 2019-04-01 施行"),
    "ff8080816f3e98bd016f41f5b268023f": ("2007-06-01", "flk sxrq 为空；国务院令第493号 2007-06-01 施行"),
    "ff8080816f3cbb3c016f40ef434b0c3e": ("1983-09-12", "flk sxrq 为空；自发布之日施行"),
    "ff8080816f3cbb3c016f411a44f7173d": ("1986-02-18", "flk sxrq 为空；自发布之日施行"),
    "ff8080816f3e9784016f41f740360220": ("1955-12-29", "flk sxrq 为空；自发布之日施行"),
    "ff8080816f3e9784016f4243e3530414": ("1990-07-11", "flk sxrq 为空；自发布之日施行"),
    "ff8080816f3e9784016f42511b5404ef": ("1981-04-06", "flk sxrq 为空；自发布之日施行"),
    "ff8080816f3cbb3c016f411bba911795": ("2000-12-01", "flk 记录为 2013 修订公布日；原条例 2000-12-01 施行"),
    "ff8080816f3cbb3c016f4129dbe61a9b": ("2005-09-03", "flk 记录为 2013 修订公布日；原规定 2005-09-03 公布施行"),
    "ff808081777d0c940177cdb0394c4fac": ("1953-01-02", "1951-02-26 公布、1953-01-02 修正公布；flk 标记已废止"),
}

# (bbbs, 是否必选核心清单 True=任务明确要求, topic/说明)
LAW_ITEMS = [
    ("ff8080816f135f46016f20f16ee11737", True, "劳动基准/劳动合同总纲"),
    ("2c909fdd678bf17901678bf74d7106b3", True, "劳动合同"),
    ("2c909fdd678bf17901678bf7b34f07df", True, "就业促进"),
    ("2c909fdd678bf17901678bf64f28039d", True, "劳动争议处理"),
    ("ff8080816f135f46016f210989b9179a", True, "社会保险"),
    ("ff8081817f072a2e017f0ae1a7f600f0", True, "集体合同与工会"),
    ("ff8081817a66b816017a7956b7db0ad4", True, "劳动安全卫生"),
    ("ff8080816f135f46016f212ea20a17f8", True, "劳动安全卫生"),
    ("ff808181841257210184281512de0eec", True, "特殊群体保护"),
    ("ff8080816f135f46016f1d134c88132b", True, "特殊群体保护"),
    ("ff8081818f197cf001905e567af635a0", True, "特殊群体保护"),
    ("2c909fdd678bf17901678bf6b19e04f1", True, "劳动安全卫生"),
    ("2c909fdd678bf17901678bf74ede06c7", True, "劳动安全卫生"),
    ("2933e1a00644487bbd43d0960cb01931", True, "劳动安全卫生"),
    ("5d298a33dc474da595bf956cec680163", True, "社会保险/医疗保障"),
    ("2c909fdd678bf17901678bf5a6740055", True, "退休退职（批准决议）"),
    ("2c909fdd678bf17901678bf5acd40087", True, "探亲待遇（批准决议）"),
    # 扩展建议：与劳动法领域强相关、数据仓库宜收录的法律
    ("ff80808171e9e18101727e38094d7e07", False, "基本医疗卫生与健康促进法（医保/职业健康背景法）"),
    ("ff8080816f135f46016f20e4396a16fb", False, "公务员法（人事关系）"),
    ("2c909fdd678bf17901678bf73e160645", False, "军人保险法（社会保险）"),
    ("58d7569a322b4eca9b22feaa4f5d7d4f", False, "仲裁法（2025 修订，劳动争议仲裁的上位程序法）"),
    ("ff8081817ba965c4017bb8921d13077a", False, "人口与计划生育法（生育保险/产假）"),
    ("ff80808175265dd40176a88c218f2853", False, "预防未成年人犯罪法（未成年人保护）"),
    ("ff8081818c9108eb018cb6922f750c07", False, "公司法（劳动合同终止/经济补偿关联）"),
    ("2c909fdd678bf17901678bf63c7c0343", False, "企业破产法（职工债权清偿顺位）"),
    ("2c909fdd678bf17901678bf8313d098d", False, "煤炭法（矿山劳动安全背景法）"),
    ("ff8080816f135f46016f21740ae61b10", False, "建筑法（建设工程安全生产/用工）"),
    ("ff808181802d2853018044c7370108c6", False, "职业教育法（职业培训）"),
    ("ff80808175265dd40175d58c08410310", False, "退役军人保障法（就业安置）"),
    ("ff8080816f135f46016f20f4bf851746", False, "老年人权益保障法（超龄劳动者/特殊群体）"),
]

ADMIN_ITEMS = [
    ("ff8080816f3cbb3c016f40927caf049c", True, "劳动合同法实施条例"),
    ("ff8080816f3cbb3c016f41114fec14e9", True, "劳动保障监察条例"),
    ("ff8080816f3cbb3c016f40d5bc0f0659", True, "工伤保险条例"),
    ("ff8080816f3cbb3c016f40f8971f0ef3", True, "失业保险条例"),
    ("ff8080816f3cbb3c016f40f97d360f29", True, "社会保险费征缴暂行条例"),
    ("ff8081818a1cb709018a6dbc91b6301d", True, "社会保险经办条例"),
    ("ff8080816f3e98bd016f420b9b460371", True, "职工带薪年休假条例"),
    ("ff8080816f3cbb3c016f410f1ed51451", True, "女职工劳动保护特别规定"),
    ("ff8080816f3cbb3c016f40a1b7230583", True, "禁止使用童工规定"),
    ("ff8081819c230ff2019c2d0fcc20642c", True, "使用有毒物品作业场所劳动保护条例"),
    ("ff8080816f3e9784016f423752750349", True, "矿山安全法实施条例"),
    ("ff8080816f3cbb3c016f40ee9ee50c0f", True, "安全生产许可证条例"),
    ("ff8080816f3cbb3c016f40ea51880ae9", True, "建设工程安全生产管理条例"),
    ("ff8081818d736ac1018dcfa3fda42e0d", True, "煤矿安全生产条例"),
    ("ff8080816f3cbb3c016f4087cdcc03d9", True, "危险化学品安全管理条例"),
    ("ff8080816f3cbb3c016f40d306b705f3", True, "特种设备安全监察条例"),
    ("ff8080816f3e9784016f4201bf5d028c", True, "关于工资总额组成的规定"),
    ("ff8080816f3cbb3c016f41260ca619e7", True, "国务院关于职工工作时间的规定"),
    ("ff8080816f3e9784016f424fe00c04e5", True, "劳动就业服务企业管理规定"),
    ("ff8080816f3cbb3c016f40fd4631102f", True, "国有企业富余职工安置规定"),
    ("ff8081819ff54a6401a01df735565134", True, "住房公积金管理条例（2026 修订）"),
    ("ff8080816f3e98bd016f41eb2b4a01cc", True, "残疾人就业条例"),
    ("ff8080816f3cbb3c016f414082e71ee1", True, "人力资源市场暂行条例"),
    ("ff808081774c7a3d01776c41674315b2", True, "保障农民工工资支付条例"),
    ("ff8080816f3cbb3c016f412e35e31b74", True, "全国社会保障基金条例"),
    ("ff808081777d07c50177be8941b04084", True, "医疗保障基金使用监督管理条例"),
    ("ff808081777d0c940177cdb0394c4fac", True, "劳动保险条例（已废止）"),
    ("ff8080816f3cbb3c016f411bba911795", True, "煤矿安全监察条例（已废止）"),
    # 扩展建议
    ("ff8080816f3cbb3c016f4125dd7719de", False, "事业单位人事管理条例"),
    ("ff8080816f3cbb3c016f4143a1591f56", False, "生产安全事故应急条例"),
    ("ff8080816f3e98bd016f41f5b268023f", False, "生产安全事故报告和调查处理条例"),
    ("ff8081818a22132f018a6e3598eb2301", False, "船员条例（涉外用工/船员劳动保护）"),
    ("ff8081819f12cdb7019f20e2bce8514c", False, "退役军人就业创业促进条例（2026 新规）"),
    ("ff8080816f3cbb3c016f4129dbe61a9b", False, "国务院关于预防煤矿生产安全事故的特别规定（已废止）"),
    ("ff8080816f3cbb3c016f40ef434b0c3e", False, "国务院关于高级专家离休退休若干问题的暂行规定"),
    ("ff8080816f3cbb3c016f411a44f7173d", False, "国务院关于高级专家退休问题的补充规定"),
    ("ff8080816f3e9784016f41f740360220", False, "国务院关于处理国家机关工作人员退职、退休时计算工作年限的暂行规定"),
    ("ff8080816f3e9784016f4243e3530414", False, "工人考核条例（职业培训）"),
    ("ff8080816f3e9784016f42511b5404ef", False, "国家机关工作人员病假期间生活待遇的规定（病假工资）"),
    ("ff8080816f3cbb3c016f4153bc772240", False, "中华人民共和国尘肺病防治条例（职业病）"),
    ("ff8080816f3cbb3c016f4120931218db", False, "国务院关于特大安全事故行政责任追究的规定（安全生产）"),
    ("ff8081819150458d019172e46a6e57be", False, "退役军人安置条例（就业安置）"),
]

JUDICIAL_ITEMS = [
    ("ff80808177e75f88017800739d621b12", True, "劳动争议解释（一）"),
    ("ff80818198a7eafa0199329bcc11687f", True, "劳动争议解释（二）"),
    ("ff808181799df4000179b0a7f8d31899", True, "工会法解释"),
    ("402881e45ffb0c10015ffb372f4c014f", True, "工伤保险行政案件规定"),
    ("402881e45ffbbe41015ffc9927c51085", True, "拒不支付劳动报酬刑事案件解释"),
    ("402881e45ffff95001600055c01c0494", True, "人事争议仲裁时效批复"),
    ("402881e45ffff95001600072f47d0686", True, "事业单位人事争议规定"),
    ("402881e45ffff9500160007c95e0078b", False, "劳动争议仲裁裁决生效时点解释"),
    ("402881e46000e279016001a56615086f", False, "劳动争议案件诉讼当事人批复"),
    ("402881e45ffbbe41015ffc12ce2404b5", False, "破产企业社会保险统筹费用批复"),
    ("402881e45ffff9500160007d27fc07a1", False, "工会法人资格及经费集中户批复（已修改）"),
    ("ff8081819c0d2f98019c227f9ccc76ae", False, "基本医疗保险基金先行支付批复（2026 新规）"),
    ("ff808081777d07c50177cdb0af7054f8", False, "涉船员纠纷规定"),
    ("ff808181799df4000179b0a6f0ae1888", False, "医疗损害责任纠纷解释"),
    ("402881e45ffb5c4c015ffb805bcf034c", False, "两高危害生产安全刑事案件解释"),
    ("402881e45ffbbe41015ffc450153086b", False, "最高检挪用失业保险基金批复"),
]

# 需用外部来源核验的条目（flk 未收录或需补充）
MANUAL_ITEMS = [
    {
        "category": "法律",
        "title": "中华人民共和国劳动法",
        "note": "见 flk 条目",
    },
]

# 部门规章（flk 不收录，需人社部/国务院部门规章库核验；标注 kernel 元数据）
DEPT_RULES = [
    ("工资支付暂行规定", "劳部发〔1994〕489号", "劳动部", "1994-12-06", "1995-01-01", "有效", "https://www.mohrss.gov.cn/"),
    ("最低工资规定", "劳动和社会保障部令第21号", "劳动和社会保障部", "2004-01-20", "2004-03-01", "有效", "https://www.mohrss.gov.cn/"),
    ("集体合同规定", "劳动和社会保障部令第22号", "劳动和社会保障部", "2004-01-20", "2004-05-01", "有效", "https://www.mohrss.gov.cn/"),
    ("劳务派遣暂行规定", "人力资源和社会保障部令第22号", "人力资源和社会保障部", "2014-01-24", "2014-03-01", "有效", "https://www.mohrss.gov.cn/"),
    ("工伤认定办法", "人力资源和社会保障部令第8号", "人力资源和社会保障部", "2010-12-31", "2011-01-01", "有效", "https://www.mohrss.gov.cn/"),
    ("企业职工带薪年休假实施办法", "人力资源和社会保障部令第1号", "人力资源和社会保障部", "2008-09-18", "2008-09-18", "有效", "https://www.mohrss.gov.cn/"),
    ("劳动人事争议仲裁办案规则", "人力资源和社会保障部令第33号", "人力资源和社会保障部", "2017-05-08", "2017-07-01", "有效", "https://www.mohrss.gov.cn/"),
    ("劳动人事争议仲裁组织规则", "人力资源和社会保障部令第34号", "人力资源和社会保障部", "2017-05-08", "2017-07-01", "有效", "https://www.mohrss.gov.cn/"),
    ("企业劳动争议协商调解规定", "人力资源和社会保障部令第17号", "人力资源和社会保障部", "2011-11-30", "2012-01-01", "有效", "https://www.mohrss.gov.cn/"),
    ("未成年工特殊保护规定", "劳部发〔1994〕498号", "劳动部", "1994-12-09", "1995-01-01", "有效", "https://www.mohrss.gov.cn/"),
    ("社会保险费申报缴纳管理规定", "人力资源和社会保障部令第20号", "人力资源和社会保障部", "2013-09-26", "2013-11-01", "有效", "https://www.mohrss.gov.cn/"),
    ("工伤职工劳动能力鉴定管理办法", "人力资源和社会保障部令第21号", "人力资源和社会保障部", "2014-02-20", "2014-04-01", "有效", "https://www.mohrss.gov.cn/"),
    ("企业年金办法", "人力资源和社会保障部、财政部令第36号", "人力资源和社会保障部、财政部", "2017-12-18", "2018-02-01", "有效", "https://www.mohrss.gov.cn/"),
    ("就业服务与就业管理规定", "劳动和社会保障部令第28号", "劳动和社会保障部", "2007-11-05", "2008-01-01", "有效", "https://www.mohrss.gov.cn/"),
    ("劳务派遣行政许可实施办法", "人力资源和社会保障部令第19号", "人力资源和社会保障部", "2013-06-20", "2013-07-01", "有效", "https://www.mohrss.gov.cn/"),
    ("工资集体协商试行办法", "劳动和社会保障部令第9号", "劳动和社会保障部", "2000-11-08", "2000-11-08", "有效", "https://www.mohrss.gov.cn/"),
]

# 历史版本 / 已废止（仅用于说明，不要求入库）
HISTORICAL = [
    ("2c909fdd678bf17901678bf6e3c00505", "中华人民共和国劳动法 2009 修正"),
    ("ff8080816f135f46016f1d16e370133e", "中华人民共和国妇女权益保障法 2018 修正"),
    ("2c909fdd678bf17901678bf632a90307", "中华人民共和国妇女权益保障法 2005 修正"),
    ("ff80808175265dd401753fb9c458127b", "中华人民共和国未成年人保护法 2020 修订"),
    ("2c909fdd678bf17901678bf746430681", "中华人民共和国未成年人保护法 2012 修正"),
    ("2c909fdd678bf17901678bf6f8a3050f", "中华人民共和国工会法 2009 修正"),
    ("2c909fdd678bf17901678bf76e990735", "中华人民共和国安全生产法 2014 修正"),
    ("2c909fdd678bf17901678bf88c0e0aff", "中华人民共和国职业病防治法 2017 修正"),
    ("2c909fdd678bf17901678bf713d305b9", "中华人民共和国社会保险法 2010"),
    ("2c909fdd678bf17901678bf6508b03b1", "中华人民共和国残疾人保障法 2008 修订"),
    ("2c909fdd678bf17901678bf8017a08b1", "中华人民共和国人口与计划生育法 2015 修正"),
    ("ff8080816f3cbb3c016f40fc7b680ff2", "住房公积金管理条例 2019 修订"),
    ("ff8080816f3e9784016f42453ffa043a", "使用有毒物品作业场所劳动保护条例 2002"),
    ("ff8080816f3e9784016f41f6358d0217", "船员条例 2019 修订"),
    ("ff808081777d0c940177b84646b02baa", "船员条例 2020 修订"),
    ("ff8080816f3cbb3c016f413b6a231df7", "乡镇煤矿管理条例（已废止）"),
    ("402881e45ffbbe41015ffca091ce10f9", "劳动争议解释（2001，已废止）"),
    ("402881e45ffbbe41015ffca7c50e11a0", "劳动争议解释（二）（2006，已废止）"),
    ("402881e45ffbbe41015ffca575fb1177", "劳动争议解释（三）（2010，已废止）"),
    ("402881e45ffbbe41015ffca32c48113d", "劳动争议解释（四）（2013，已废止）"),
    ("402881e46000e2790160013834320071", "解除劳动合同仲裁申请期限批复（已废止）"),
    ("402881e45ffff9500160009008fd08cd", "劳动争议仲裁逾期不裁决批复（已废止）"),
    ("402881e45ffbbe41015ffc787db10da4", "审理企业破产案件指定管理人的规定（关联）"),
    ("2c90e5bb65c68cfd0167f25968bf4d40", "仲裁司法审查报核规定 2017（已修改）"),
    ("402881e45ffb5c4c015ffb6aa3850159", "工会法解释 2003（已修改）"),
]


def main() -> None:
    pool = {r["bbbs"]: r for r in json.loads((CACHE / "pool.json").read_text())}
    for f in ("list_laws.json", "list_admin_regs.json", "list_judicial.json"):
        for r in json.loads((CACHE / f).read_text()):
            pool.setdefault(r["bbbs"], r)
    # 列表缓存中未命中关键词但确需收录的条目，补充抓取记录（人工核对过 bbbs）
    extra = {
        "ff8080816f3e9784016f42511b5404ef": {
            "bbbs": "ff8080816f3e9784016f42511b5404ef",
            "title": "国家机关工作人员病假期间生活待遇的规定",
            "gbrq": "1981-04-06", "sxrq": None, "sxx": 3,
            "zdjgName": "国务院", "flfgCodeId": 210,
        },
    }
    pool.update(extra)

    items = []
    seen = set()

    def add(bbbs: str, level: str, required: bool, topic: str) -> None:
        r = pool.get(bbbs)
        if not r:
            print("!! 未在缓存中找到", bbbs, level)
            return
        if bbbs in seen:
            return
        seen.add(bbbs)
        prom = r.get("gbrq") or ""
        eff = r.get("sxrq") or ""
        note_parts = []
        if bbbs in EFFECTIVE_FIX:
            eff, why = EFFECTIVE_FIX[bbbs]
            note_parts.append(why)
        sxx = r.get("sxx")
        items.append({
            "category": level,
            "title": r["title"],
            "issuer": r.get("zdjgName") or "",
            "promulgated": prom,
            "effective": eff,
            "sxx": sxx,
            "status": SXX.get(sxx, ""),
            "current": {1: "否（已废止）", 2: "否（已被修改，另有现行版本）",
                        3: "是", 4: "否（尚未生效）"}.get(sxx, ""),
            "bbbs": bbbs,
            "flfgCodeId": r.get("flfgCodeId"),
            "required": required,
            "topic": topic,
            "source_url": "https://flk.npc.gov.cn/detail?title=" + __import__("urllib.parse").parse.quote(r["title"]) + "&bbbs=" + bbbs,
            "note": "；".join(note_parts),
        })

    for bb, req, topic in LAW_ITEMS:
        add(bb, "法律", req, topic)
    for bb, req, topic in ADMIN_ITEMS:
        if not bb.isalnum():
            continue
        add(bb, "行政法规", req, topic)
    for bb, req, topic in JUDICIAL_ITEMS:
        add(bb, "司法解释", req, topic)

    # 部门规章（flk 无）——清单由 _mohrss_rules.py 全量提供，此处不入 items.json
    for title, num, issuer, prom, eff, status, url in []:
        items.append({
            "category": "部门规章",
            "title": title,
            "issuer": issuer,
            "promulgated": prom,
            "effective": eff,
            "sxx": 3 if status == "有效" else "",
            "status": status,
            "current": "是" if status == "有效" else status,
            "bbbs": "",
            "flfgCodeId": None,
            "required": True,
            "topic": "部门规章",
            "doc_number": num,
            "source_url": url,
            "note": "flk 不收录部门规章，需以人社部官网/国务院部门规章库核验",
        })

    # 两部由全国人大批准的行政法规本体（flk 仅收录批准决议）
    items.append({
        "category": "行政法规",
        "title": "国务院关于工人退休、退职的暂行办法",
        "issuer": "国务院",
        "promulgated": "1978-06-02",
        "effective": "1978-06-02",
        "sxx": 3, "status": "有效", "current": "是",
        "bbbs": "", "flfgCodeId": None, "required": True,
        "topic": "退休退职",
        "source_url": "https://www.gov.cn/",
        "note": "1978-05-24 全国人大常委会原则批准，国务院 1978-06-02 发布；flk 仅收录批准决议(bbbs=2c909fdd678bf17901678bf5a6740055)，本体以 gov.cn 核验",
    })
    items.append({
        "category": "行政法规",
        "title": "关于安置老弱病残干部的暂行办法",
        "issuer": "国务院",
        "promulgated": "1978-06-02",
        "effective": "1978-06-02",
        "sxx": 3, "status": "有效", "current": "是",
        "bbbs": "", "flfgCodeId": None, "required": False,
        "topic": "退休退职",
        "source_url": "https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/202509/t20250929_4214107.html",
        "note": "国发〔1978〕104号颁发，官方全称《国务院关于安置老弱病残干部的暂行办法》；flk 未收录，正文来源为北京市政府网（国务院文件转载）",
    })
    items.append({
        "category": "行政法规",
        "title": "国务院关于职工探亲待遇的规定",
        "issuer": "国务院",
        "promulgated": "1981-03-14",
        "effective": "1981-03-14",
        "sxx": 3, "status": "有效", "current": "是",
        "bbbs": "", "flfgCodeId": None, "required": True,
        "topic": "探亲待遇",
        "source_url": "https://www.gov.cn/",
        "note": "1981-03-06 全国人大常委会批准，国务院 1981-03-14 公布施行；flk 仅收录批准决议(bbbs=2c909fdd678bf17901678bf5acd40087)，本体以 gov.cn 核验",
    })

    for it in items:
        it["flk_content_tree"] = (
            it["bbbs"] not in ("2933e1a00644487bbd43d0960cb01931",  # 危险化学品安全法
                               "5d298a33dc474da595bf956cec680163",   # 医疗保障法
                               "58d7569a322b4eca9b22feaa4f5d7d4f",   # 仲裁法
                               "2c909fdd678bf17901678bf5a6740055",   # 退休退职决议
                               "2c909fdd678bf17901678bf5acd40087")   # 探亲决议
            and it["category"] == "法律"
        )
    out = {
        "generated": "2026-11-10",
        "source": "flk.npc.gov.cn 列表缓存 + 人社部规章清单（待核验标注）",
        "items": items,
        "historical": [{"bbbs": b, "note": n} for b, n in HISTORICAL],
    }
    (HERE / "items.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"items: {len(items)}")
    from collections import Counter
    print(Counter(i["category"] for i in items))
    print("required:", sum(1 for i in items if i["required"]))
    for i in items:
        print(f'{i["category"]:5s} {i["status"]:4s} {i["promulgated"]:10s} {i["effective"]:10s} {i["bbbs"]:32s} {i["title"]}')


if __name__ == "__main__":
    main()
