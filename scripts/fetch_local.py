#!/usr/bin/env python3
"""Fetch 地方性法规 (flfgCodeId=230) in the labour/social-security domain.

Pipeline
--------
1. ``sweep``  : title-search (searchType=1) every keyword, page through all
                results, dedupe by ``bbbs`` -> research/local/candidates.json
2. ``filter`` : relevance rules -> research/local/selected.json
3. ``fetch``  : docx download -> raw/local/<bbbs>.docx -> data/local-regulations/
                <province>/<title>-<year>.md  (idempotent; skips existing)
4. ``index``  : research/local/index.json

The WAF in front of flk.npc.gov.cn answers a JS challenge (WZWS) for GET
requests when it feels like it.  ``_waf_get()`` solves the challenge in Node
(the page JS just assigns ``window.location = "/WZWSREL<base64>?..."``) and
retries, falling back to a long cooldown if that fails.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from flk_client import BASE, UA, FlkClient, FlkError, clean_title  # noqa: E402
import docx2md  # noqa: E402

RAW = ROOT / "raw" / "local"
DATA = ROOT / "data" / "local-regulations"
RESEARCH = ROOT / "research" / "local"
RETRIEVED = "2026-11-10"

KEYWORDS = [
    "劳动", "劳动合同", "工资", "工时", "休息", "休假", "社会保险", "社保",
    "工伤", "失业", "就业", "职业培训", "工会", "职工", "集体合同", "劳务派遣",
    "劳动争议", "劳动保障监察", "劳动监察", "最低工资", "童工", "未成年工",
    "女职工", "农民工", "欠薪", "退休", "劳动保护", "生育保险", "住房公积金",
    "安全生产", "职业病", "职业卫生", "人力资源市场", "企业年金", "社会保障",
    # 补充召回（任务关键词为“至少含”）：社保各险种、劳动关系/民主管理/职业培训
    "养老保险", "医疗保险", "工伤保险", "社会保险费", "劳动关系", "集体协商",
    "职工代表大会", "民主管理", "劳动能力鉴定", "工伤认定", "职业健康",
    "职业技能", "职工教育", "就业援助", "人力资源",
]

# zdjgCodeId -> 省级行政区（flk 的制定机关代码按省份每 10 一个）
PROVINCE_BY_CODE = {
    170: "北京市", 180: "天津市", 190: "河北省", 200: "山西省",
    210: "内蒙古自治区", 220: "辽宁省", 230: "吉林省", 240: "黑龙江省",
    250: "上海市", 260: "江苏省", 270: "浙江省", 280: "安徽省",
    290: "福建省", 300: "江西省", 310: "山东省", 320: "河南省",
    330: "湖北省", 340: "湖南省", 350: "广东省", 360: "广西壮族自治区",
    370: "海南省", 380: "重庆市", 390: "四川省", 400: "贵州省",
    410: "云南省", 420: "西藏自治区", 430: "陕西省", 440: "甘肃省",
    450: "青海省", 460: "宁夏回族自治区", 470: "新疆维吾尔自治区",
}

# 城市/州/盟 -> 省（只在 code 缺失/9999 时兜底）
CITY_TO_PROVINCE = {}


def _add(city: str, prov: str) -> None:
    CITY_TO_PROVINCE[city] = prov


for c in ["石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德",
          "沧州", "廊坊", "衡水"]:
    _add(c, "河北省")
for c in ["太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州",
          "临汾", "吕梁"]:
    _add(c, "山西省")
for c in ["呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔",
          "巴彦淖尔", "乌兰察布", "兴安盟", "锡林郭勒盟", "阿拉善盟"]:
    _add(c, "内蒙古自治区")
for c in ["沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新",
          "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛"]:
    _add(c, "辽宁省")
for c in ["长春", "吉林", "四平", "辽源", "通化", "白山", "松原", "白城", "延边"]:
    _add(c, "吉林省")
for c in ["哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯",
          "七台河", "牡丹江", "黑河", "绥化", "大兴安岭"]:
    _add(c, "黑龙江省")
for c in ["南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城",
          "扬州", "镇江", "泰州", "宿迁"]:
    _add(c, "江苏省")
for c in ["杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山",
          "台州", "丽水"]:
    _add(c, "浙江省")
for c in ["合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山",
          "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城"]:
    _add(c, "安徽省")
for c in ["福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德"]:
    _add(c, "福建省")
for c in ["南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春",
          "抚州", "上饶"]:
    _add(c, "江西省")
for c in ["济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安",
          "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽"]:
    _add(c, "山东省")
for c in ["郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳",
          "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店",
          "济源"]:
    _add(c, "河南省")
for c in ["武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州",
          "黄冈", "咸宁", "随州", "恩施", "仙桃", "潜江", "天门", "神农架"]:
    _add(c, "湖北省")
for c in ["长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳",
          "郴州", "永州", "怀化", "娄底", "湘西"]:
    _add(c, "湖南省")
for c in ["广州", "韶关", "深圳", "珠海", "汕头", "佛山", "江门", "湛江", "茂名",
          "肇庆", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山",
          "潮州", "揭阳", "云浮"]:
    _add(c, "广东省")
for c in ["南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林",
          "百色", "贺州", "河池", "来宾", "崇左"]:
    _add(c, "广西壮族自治区")
for c in ["海口", "三亚", "三沙", "儋州"]:
    _add(c, "海南省")
for c in ["成都", "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江",
          "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳",
          "阿坝", "甘孜", "凉山"]:
    _add(c, "四川省")
for c in ["贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南", "黔东南",
          "黔南"]:
    _add(c, "贵州省")
for c in ["昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "楚雄",
          "红河", "文山", "西双版纳", "大理", "德宏", "怒江", "迪庆"]:
    _add(c, "云南省")
for c in ["拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里"]:
    _add(c, "西藏自治区")
for c in ["西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康",
          "商洛"]:
    _add(c, "陕西省")
for c in ["兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉",
          "庆阳", "定西", "陇南", "临夏", "甘南"]:
    _add(c, "甘肃省")
for c in ["西宁", "海东", "海北", "黄南", "海南州", "果洛", "玉树", "海西"]:
    _add(c, "青海省")
for c in ["银川", "石嘴山", "吴忠", "固原", "中卫"]:
    _add(c, "宁夏回族自治区")
for c in ["乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞",
          "阿克苏", "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰",
          "石河子", "阿拉尔", "图木舒克", "五家渠"]:
    _add(c, "新疆维吾尔自治区")

PROVINCES = list(PROVINCE_BY_CODE.values())


# --------------------------------------------------------------------- helpers
def issuer_key(name: str) -> str:
    """'北京市人民代表大会常务委员会' -> '北京市' (name part before the organ)."""
    s = (name or "").strip()
    s = re.sub(r"\s+", "", s)
    for suffix in [
        "人民代表大会常务委员会", "人大常务委员会", "人大常委会",
        "人民代表大会", "人民政府", "人大",
    ]:
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def province_of(row: dict) -> str | None:
    code = row.get("zdjgCodeId")
    prov = PROVINCE_BY_CODE.get(code)
    if prov:
        return prov
    key = issuer_key(row.get("zdjgName") or "")
    if key in PROVINCES:
        return key
    # 城市名可能带“市/州/盟/地区”后缀或为自治州全名
    for city, p in CITY_TO_PROVINCE.items():
        if key.startswith(city):
            return p
    # 自治区名称变体
    for p in PROVINCES:
        if key.startswith(p[:4]):
            return p
    return None


# ------------------------------------------------------------------- WAF solve
SOLVER = SCRIPTS / "waf_solver.js"


def solve_waf(html_bytes: bytes) -> str | None:
    """Run the Node challenge solver on a WAF challenge page -> pass URL."""
    with tempfile.TemporaryDirectory() as td:
        hp = Path(td) / "challenge.html"
        hp.write_bytes(html_bytes)
        try:
            out = subprocess.run(
                ["node", str(SOLVER), str(hp), "--json"],
                capture_output=True, text=True, timeout=40)
        except Exception:
            return None
        if out.returncode != 0:
            if out.stderr:
                print("  ~ solver:", out.stderr.strip()[:200])
            return None
        try:
            return json.loads(out.stdout)["pass_url"]
        except Exception:
            return None


def is_challenge(blob: bytes, ctype: str) -> bool:
    if "json" in ctype.lower():
        return False
    head = blob[:400].lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html") or b"wzws" in blob[:4000].lower()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class HttpClient:
    """urllib session with WZWS challenge solving + polite rate limiting."""

    def __init__(self, min_interval: float = 1.35, verbose: bool = False):
        import http.cookiejar

        self.min_interval = min_interval
        self.verbose = verbose
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self._last = 0.0
        self.challenges = 0
        self.solves = 0

    def _sleep(self):
        dt = time.time() - self._last
        wait = self.min_interval + (0.3 * (hash(str(time.time())) % 100) / 100.0) - dt
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _raw(self, url: str, headers: dict | None = None, timeout: int = 60):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        with self.op.open(req, timeout=timeout) as r:
            return r.status, r.headers, r.read()

    def pass_challenge(self, blob: bytes) -> bool:
        """Run the challenge JS and visit the URL it computes."""
        self.challenges += 1
        loc = solve_waf(blob)
        if not loc:
            if self.verbose:
                print("  ~ challenge solve failed")
            return False
        if loc.startswith("/"):
            loc = BASE + loc
        elif not loc.startswith("http"):
            loc = BASE + "/" + loc
        try:
            self._sleep()
            self._raw(loc, timeout=40)
            self.solves += 1
            return True
        except Exception:
            return False

    def get_json(self, url: str, tries: int = 4) -> dict:
        last: Exception | None = None
        for attempt in range(tries):
            self._sleep()
            try:
                st, hd, blob = self._raw(url)
                ct = hd.get("Content-Type", "")
                if is_challenge(blob, ct):
                    if self.verbose:
                        print(f"  ~ WAF challenge on {url[:80]} (try {attempt+1})")
                    if self.pass_challenge(blob):
                        continue
                    time.sleep(150)
                    continue
                return json.loads(blob)
            except Exception as e:  # noqa: BLE001
                last = e
                if self.verbose:
                    print(f"  ! request error {type(e).__name__}: {e}")
                time.sleep(5 + 5 * attempt)
        raise FlkError(f"get_json failed after {tries} tries: {url}: {last}")

    def get_binary(self, url: str, tries: int = 3, delay: bool = True) -> tuple[bytes, dict]:
        last: Exception | None = None
        for attempt in range(tries):
            if delay:
                self._sleep()
            try:
                st, hd, blob = self._raw(url)
                ct = hd.get("Content-Type", "")
                if is_challenge(blob, ct):
                    if self.verbose:
                        print("  ~ WAF challenge on download")
                    if self.pass_challenge(blob):
                        continue
                    time.sleep(150)
                    continue
                return blob, dict(hd)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(5 + 5 * attempt)
        raise FlkError(f"get_binary failed after {tries} tries: {url}: {last}")

    def download_docx(self, bbbs: str, dest: Path, tries: int = 4) -> Path:
        """下载 docx：先拿 302 到 OBS 签名地址，再取二进制；遇 WAF 先解挑战。"""
        if dest.exists() and dest.stat().st_size > 1024:
            return dest
        dl = (BASE + "/law-search/download/mobile?"
              + urllib.parse.urlencode({"format": "docx", "bbbs": bbbs, "fileId": ""}))
        last: Exception | None = None
        for attempt in range(tries):
            self._sleep()
            req = urllib.request.Request(dl)
            req.add_header("User-Agent", UA)
            req.add_header("Referer", BASE + "/detail")
            op = urllib.request.build_opener(
                _NoRedirect(), urllib.request.HTTPCookieProcessor(self.cj))
            loc = None
            body = b""
            ctype = ""
            try:
                with op.open(req, timeout=60) as resp:
                    body = resp.read()
                    ctype = resp.headers.get("Content-Type", "")
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                    loc = e.headers["Location"]
                else:
                    last = e
                    time.sleep(5 + 5 * attempt)
                    continue
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(5 + 5 * attempt)
                continue
            if loc is None:
                if is_challenge(body, ctype):
                    if self.verbose:
                        print("  ~ WAF challenge on download URL")
                    if self.pass_challenge(body):
                        continue
                last = FlkError(f"download returned {ctype} {len(body)}b")
                time.sleep(150)
                continue
            try:
                blob, hd = self.get_binary(loc, delay=False)  # OBS 签名地址，非 flk WAF
            except FlkError as e:
                last = e
                continue
            if len(blob) < 800:
                last = FlkError(f"downloaded blob too small: {len(blob)}")
                continue
            if is_challenge(blob, hd.get("Content-Type", "")):
                last = FlkError("OBS returned challenge page")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
            return dest
        raise FlkError(f"download failed after {tries} tries: {bbbs}: {last}")


# ------------------------------------------------------------------- properties
STRONG = [
    "劳动", "劳动合同", "工资", "工时", "休息", "休假", "社会保险", "社保",
    "工伤", "失业", "就业", "职业培训", "工会", "职工", "集体合同", "劳务派遣",
    "劳动争议", "劳动保障监察", "劳动监察", "最低工资", "童工", "未成年工",
    "女职工", "农民工", "欠薪", "退休", "劳动保护", "生育保险", "住房公积金",
    "企业年金", "社会保障", "雇员", "聘用", "薪酬", "劳动能力鉴定",
    "人力资源市场", "职业病", "职业卫生", "职业健康", "养老保险", "医疗保险",
    "工伤保险", "社会保险费", "劳动关系", "集体协商", "职工代表大会",
    "民主管理", "工伤认定", "职业技能", "职工教育", "就业援助",
]

# 明确与劳动无关的主题：命中即排除（标题层面，无例外）
HARD_EXCLUDE = [
    "劳动教育", "社会保障卡", "社会保障性住房", "社会保障资金", "社会保障基金",
    "医疗保障基金", "医保基金", "社会保险基金监督", "志愿者", "文明行为",
    "社会信用", "学校安全", "食品安全", "建筑质量", "物业服务", "物业管理",
    "城市管理", "市容", "环境卫生", "殡葬", "犬只", "旅游", "交通管理",
    "烟花爆竹", "历史文化", "文物保护", "湿地", "绿化", "供水", "节水",
    "燃气", "供热", "医疗纠纷", "医疗机构", "养老服务", "养老机构", "养老设施",
    "公积金贷款", "住房公积金管理委员会", "就餐休息",
]

# 主题弱（养老/医疗/安全），只有同时命中劳动相关词才收
WEAK_TOPICS = ["安全生产", "生产安全", "消防", "特种设备", "矿山", "职业病",
               "职业卫生", "医疗保障", "医疗保险", "人力资源市场", "人才市场"]

DECISION_HINT = re.compile(
    r"(关于(修改|废止|修正).*(的决定|决议)|修改<|的决定$|废止$|修正案?$)")


def clean_title_of(title: str) -> str:
    t = clean_title(title)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def relevance(row: dict) -> tuple[bool, str]:
    title = clean_title_of(row.get("title", ""))
    t = title.replace(" ", "")
    flat = re.sub(r"[《》()（）]", "", t)
    for w in HARD_EXCLUDE:
        if w in flat:
            return False, f"excluded:{w}"
    if DECISION_HINT.search(title):
        return False, "decision"
    hits = [k for k in STRONG if k in flat]
    if hits:
        return True, "hit:" + ",".join(hits[:3])
    weak = [k for k in WEAK_TOPICS if k in flat]
    if weak:
        laborish = [k for k in ["职工", "劳动者", "从业", "雇员", "劳动"] if k in flat]
        if laborish:
            return True, "weak+" + ",".join(weak[:2])
        return False, "weak-only:" + ",".join(weak[:2])
    return False, "no-hit"


TOPIC_MAP = [
    (["劳动合同", "劳务派遣", "集体合同", "劳动关系"], "劳动合同"),
    (["集体合同", "工会", "职工代表大会", "民主管理", "职工民主"], "集体合同与工会"),
    (["工资", "最低工资", "欠薪", "薪酬", "工资支付", "工资集体协商"], "工资保障"),
    (["工时", "休息", "休假", "加班"], "劳动基准"),
    (["劳动保护", "安全生产", "职业病", "职业卫生", "女职工", "未成年工", "童工",
      "工伤预防", "矿山安全", "特种作业", "劳动安全"], "劳动安全卫生"),
    (["女职工", "未成年工", "童工", "农民工", "残疾人", "退役军人", "妇女"],
     "特殊群体保护"),
    (["社会保险", "社保", "工伤", "失业", "养老", "医疗", "生育保险", "住房公积金",
      "企业年金", "退休"], "社会保险"),
    (["就业", "职业培训", "人力资源市场", "劳动力市场", "人才", "职业技能", "创业"], "就业促进"),
    (["劳动争议", "调解", "仲裁"], "劳动争议处理"),
    (["劳动监察", "劳动保障监察", "监察", "执法"], "劳动保障监察"),
]


def topics_of(title: str) -> list[str]:
    t = title.replace(" ", "")
    out: list[str] = []
    for kws, topic in TOPIC_MAP:
        if any(k in t for k in kws) and topic not in out:
            out.append(topic)
    if not out:
        out = ["综合/其他"]
    return out[:4]


def parse_ymd(s) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


STATUS = {1: ("已废止", 1), 2: ("已修改", 2), 3: ("有效", 3), 4: ("尚未生效", 4)}


# ------------------------------------------------------------------ phase: sweep
def cmd_sweep(args) -> None:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    cache = RESEARCH / "candidates.json"
    known: dict[str, dict] = {}
    if cache.exists() and not args.refresh:
        for r in json.loads(cache.read_text(encoding="utf-8")):
            known[r["bbbs"]] = r
        print(f"resume: {len(known)} cached candidates")
    client = FlkClient(min_interval=args.interval, verbose=True)
    for kw in KEYWORDS:
        if kw in (args.skip or []) or any(k.get("kw") == kw for k in known.values()):
            print(f"[skip] {kw}")
            continue
        page, got, total = 1, 0, None
        while True:
            try:
                data = client.list_page(page=page, size=100, search_content=kw,
                                        search_type=1, codes=[230])
            except FlkError as e:
                print(f"[FAIL] list {kw} p{page}: {e}")
                break
            rows = data.get("rows") or []
            total = data.get("total") or 0
            for row in rows:
                bb = row["bbbss"] if "bbbss" in row else row["bbbs"]
                if bb not in known:
                    known[bb] = {
                        "bbbs": bb,
                        "title": clean_title_of(row.get("title", "")),
                        "gbrq": parse_ymd(row.get("gbrq")),
                        "sxrq": parse_ymd(row.get("sxrq")),
                        "sxx": row.get("sxx"),
                        "zdjgName": (row.get("zdjgName") or "").strip(),
                        "zdjgCodeId": row.get("zdjgCodeId"),
                        "flfgCodeId": row.get("flfgCodeId"),
                        "kw": kw,
                        "kw_all": [kw],
                    }
                else:
                    if kw not in known[bb]["kw_all"]:
                        known[bb]["kw_all"].append(kw)
            got += len(rows)
            print(f"[list] {kw} p{page}: {len(rows)} rows (total={total}, got={got})")
            if len(rows) < 100 or page * 100 >= total:
                break
            page += 1
        cache.write_text(json.dumps(list(known.values()), ensure_ascii=False, indent=1),
                         encoding="utf-8")
        time.sleep(0.3)
    rows = list(known.values())
    cache.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"candidates: {len(rows)} unique -> {cache}")


# ----------------------------------------------------------------- phase: filter
def cmd_filter(args) -> None:
    cand = json.loads((RESEARCH / "candidates.json").read_text(encoding="utf-8"))
    selected, dropped = [], []
    for r in cand:
        ok, reason = relevance(r)
        prov = province_of(r)
        if ok and not prov:
            ok, reason = False, "no-province"
        if ok:
            r["province"] = prov
            r["reason"] = reason
            r["topics"] = topics_of(r["title"])
            selected.append(r)
        else:
            r["reason"] = reason
            dropped.append(r)
    (RESEARCH / "selected.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=1), encoding="utf-8")
    (RESEARCH / "dropped.json").write_text(
        json.dumps(dropped, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"selected {len(selected)} / candidates {len(cand)}; dropped {len(dropped)}")
    from collections import Counter
    print("by province:", dict(sorted(Counter(r["province"] for r in selected).items())))
    bad = [r for r in selected if not r.get("gbrq")]
    print(f"missing gbrq: {len(bad)}")
    for r in bad[:10]:
        print("  ", r["bbbs"], r["title"], r["zdjgName"])


# ------------------------------------------------------------------ phase: fetch
def docx_to_text(docx_path: Path) -> Path:
    """pandoc needs OOXML; convert legacy .doc via LibreOffice first."""
    head = docx_path.read_bytes()[:8]
    if head.startswith(b"\xd0\xcf\x11\xe0"):  # OLE2 = .doc
        cached = docx_path.with_suffix(".ooxml.docx")
        if cached.exists() and cached.stat().st_size > 1024:
            return cached
        outdir = docx_path.parent
        tmp = outdir / (docx_path.stem + "_conv")
        tmp.mkdir(exist_ok=True)
        subprocess.run(
            ["soffice", "--headless", "--norestore", "--convert-to", "docx",
             "--outdir", str(tmp), str(docx_path)],
            check=True, capture_output=True, timeout=180)
        made = list(tmp.glob("*.docx"))
        if not made:
            raise RuntimeError(f"libreoffice produced no docx for {docx_path}")
        target = docx_path.with_suffix(".ooxml.docx")
        shutil.move(str(made[0]), str(target))
        shutil.rmtree(tmp, ignore_errors=True)
        return target
    return docx_path


def unique_dest(dest: Path, bbbs: str) -> Path:
    """同一标题同一年份的多个版本：若已存在文件属于别的 bbbs，加后缀区分。"""
    if not dest.exists():
        return dest
    try:
        head = dest.read_text(encoding="utf-8", errors="ignore")[:500]
    except Exception:
        head = ""
    if f"id: flk-{bbbs}" in head:
        return dest
    return dest.with_name(f"{dest.stem}-{bbbs[:8]}{dest.suffix}")


def safe_name(title: str) -> str:
    t = re.sub(r"[/\\:*?\"<>|\n\r\t]", "_", title).strip()
    t = t.replace("《", "《").strip(" .")
    return t[:120]


def _norm_title(t: str) -> str:
    t = re.sub(r"[\s　《》〈〉（）()]", "", t or "")
    return t.strip("*").strip()


def _norm_zhuti(t: str) -> str:
    t = t.replace("**", "").replace("\u200b", "")
    t = re.sub(r"^(?:>\s*)+", "", t.strip())
    t = re.sub(r"(\d{4})\s+(?=年)", r"\1", t)
    t = re.sub(r"(\d{1,2})\s+(?=[月日])", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def _merge_zhuti(lines: list[str]) -> list[str]:
    """把 docx 断成多行的官方题注（「（…通过…批准…）」）合并成一段。"""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if s.startswith("# "):
            out.append(ln)
            i += 1
            continue
        cand = _norm_zhuti(s)
        if cand.startswith(("（", "(")):
            if not cand.endswith(("）", ")")):
                parts = [cand]
                j = i + 1
                while j < n and j - i < 40:
                    nxt = lines[j].strip()
                    if nxt == "" or re.fullmatch(r"[>|\s]+", nxt or ""):
                        j += 1
                        continue
                    if nxt.startswith("#"):
                        break
                    nxt2 = re.sub(r"^(?:>\s*)+", "", nxt).strip()
                    nxt2 = nxt2.strip("| ").strip()
                    parts.append(nxt2)
                    j += 1
                    if nxt2.endswith("）") or nxt2.endswith(")"):
                        break
                merged = _norm_zhuti("".join(parts))
                out.append(merged)
                out.append("")
                i = j
                continue
            out.append(_norm_zhuti(cand))
            i += 1
            continue
        out.append(ln)
        i += 1
    return out


def cleanup_md(md: str, title: str) -> str:
    """归一化 docx→md 的版式噪声（不改动条文文字）。

    - 去零宽字符；`[第二章 …](\\l)` 目录内链 -> 纯文本
    - 去空标题、与标题重复的独立行（docx 标题/加粗标题）
    - 合并被 docx 硬换行切碎的官方题注
    - 删除 "目 录" 及其后的章节目录块，统一章/节标题层级
    """
    text = md.replace("\r\n", "\n").replace("\r", "\n")
    for ch in ("\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\ufeff"):
        text = text.replace(ch, "")
    # WPS/Word 私有区字符（\ue000-\uf8ff）是软换行/域标记，去掉
    text = re.sub("[\ue000-\uf8ff]", "", text)
    lines = [ln.rstrip() for ln in text.split("\n")]
    # pandoc 把缩进段落变成代码块/列表：法规正文不需要缩进
    lines = [ln if ln.lstrip().startswith(">") else ln.lstrip(" \t") for ln in lines]
    lines = [re.sub(r"\[([^\]]*)\]\(\\+l\)", r"\1", ln) for ln in lines]
    # pandoc 残留：HTML 标签/实体、docx 超链接 -> 纯文本
    tag_re = re.compile(
        r"</?(?:span|sup|sub|br|u|b|i|em|strong|font|div|p|a|img|small|big|"
        r"td|tr|table|tbody|thead|tfoot|th|caption|colgroup|col|"
        r"blockquote|ol|ul|li|dl|dt|dd|h[1-6]|center|hr|pre|code|"
        r"section|article|header|footer|figure|figcaption|o:p)\b[^>]*>", re.I)
    lines = [tag_re.sub("", ln) for ln in lines]
    lines = [html_mod.unescape(ln) if "&" in ln else ln for ln in lines]
    link_re = re.compile(r"\[([^\[\]]+)\]\((?:\\.|[^()\\])*\)")
    fixed = []
    for ln in lines:
        for _ in range(3):
            nxt = link_re.sub(r"\1", ln)
            if nxt == ln:
                break
            ln = nxt
        fixed.append(ln)
    lines = fixed
    # markdown 引用标记（pandoc 对某些段的误判）去掉
    lines = [re.sub(r"^(?:>\s*)+", "", ln) for ln in lines]
    # docx 里整段加粗的“伪标题/伪题注”去掉 **，按纯文本归一化
    lines = [ln.replace("**", "") for ln in lines]
    lines = ["" if re.match(r"^#{1,6}\s*$", ln.strip()) else ln for ln in lines]
    # 孤立 blockquote 标记、扫描件"附件N"标记
    lines = ["" if re.fullmatch(r"[>|｜\s　]+", ln) else ln for ln in lines]
    lines = ["" if re.fullmatch(r"附件\s*[一二三四五六七八九十\d]{0,3}", ln.strip()) else ln
             for ln in lines]

    t = _norm_title(title)
    kept = []
    for ln in lines:
        core = ln.strip()
        core = re.sub(r"^#{1,6}\s*", "", core)
        core = re.sub(r"^\*\*(.*)\*\*$", r"\1", core).strip()
        core = re.sub(r"^(?:>\s*)+", "", core).strip()
        if (core and _norm_title(core) == t and not ln.strip().startswith("# ")
                and not re.match(r"^第[一二三四五六七八九十百零〇两]+条", core)):
            continue
        kept.append(ln)
    lines = kept

    # 标题本身被 docx 折成多行（"XX省人大常委会关于" / "对符合…" / "…意见"）
    if lines and lines[0].startswith("# ") and t:
        idxs = [i for i in range(1, min(len(lines), 9)) if lines[i].strip()]
        joined = ""
        cut = []
        for i in idxs:
            sline = lines[i].strip()
            frag = re.sub(r"^#+\s*", "", sline).strip() if sline.startswith("#") else sline
            if frag.startswith(("（", "(", ">")):
                break
            frag = _norm_title(frag)
            if not frag:
                continue
            joined += frag
            cut.append(i)
            if joined == t:
                break
            if not t.startswith(joined):
                cut = []
                break
        if cut and joined == t:
            lines = [ln for i, ln in enumerate(lines) if i not in set(cut)]

    lines = _merge_zhuti(lines)

    toc_idx = None
    for i, ln in enumerate(lines):
        if re.sub(r"[\s　]+", "", ln.strip()) == "目录":
            toc_idx = i
            break
    if toc_idx is not None:
        art = None
        for j in range(toc_idx + 1, len(lines)):
            if re.match(r"^第[一二三四五六七八九十百零〇两]+条", lines[j].strip()):
                art = j
                break
        if art is not None:
            body = art
            # 第一条之前紧邻的章/节标题属于正文，不要删
            j = body - 1
            while j > toc_idx:
                sline = lines[j].strip()
                if not sline:
                    j -= 1
                    continue
                if re.match(r"^#{0,6}\s*第[一二三四五六七八九十百零〇两]+[编章节]", sline) or \
                        re.match(r"^\d{1,2}\.\s+[\s　]*[\u4e00-\u9fa5]{1,8}$", sline):
                    body = j
                    j -= 1
                    continue
                break
            del lines[toc_idx:body]

    # 丢 TOC 残留的孤章标题（出现在第一条之前且编号大于其后章标题）
    first_art = None
    for i, ln in enumerate(lines):
        if re.match(r"^#{0,6}\s*第[一二三四五六七八九十百零〇两]+条", ln.strip()) and "章" not in ln[:6]:
            first_art = i
            break
    if first_art:
        chs = [i for i in range(first_art)
               if re.match(r"^(?:#+\s*)?第([一二三四五六七八九十百零〇两]+)章", lines[i].strip())]
        if len(chs) > 1:
            def _num(i):
                mm = re.match(r"^(?:#+\s*)?第([一二三四五六七八九十百零〇两]+)章", lines[i].strip())
                try:
                    return docx2md.cn2int(mm.group(1))
                except ValueError:
                    return 0
            drop = set()
            for a in range(len(chs) - 1):
                if _num(chs[a]) > _num(chs[a + 1]):
                    drop.add(chs[a])
            lines = [ln for i, ln in enumerate(lines) if i not in drop]

    ch_plain = re.compile(
        r"^第([一二三四五六七八九十百零〇两]+)([编章节])"
        r"(?:[\s　]+([\u4e00-\u9fa5][\u4e00-\u9fa5\s　、，]{0,16}))?$")
    norm = []
    for ln in lines:
        st = ln.strip()
        m = re.match(r"^#{1,6}\s+(.*)$", st)
        if m:
            h = m.group(1).strip()
            if h.startswith(("（", "(")):       # 官方题注被误升级成标题
                ln = h
            elif re.match(r"^第[一二三四五六七八九十百零〇两]+[编章]", h):
                ln = "## " + h
            elif re.match(r"^第[一二三四五六七八九十百零〇两]+节", h):
                ln = "### " + h
        else:
            mm = ch_plain.match(st)
            if mm:
                ln = ("### " if mm.group(2) == "节" else "## ") + st
        norm.append(ln)
    lines = norm

    heads = [(i, re.sub(r"[\s　]+", "", re.sub(r"^#{1,6}\s+", "", ln.strip())))
             for i, ln in enumerate(lines) if re.match(r"^#{1,6}\s+", ln.strip())]
    if heads:
        from collections import Counter
        cnt = Counter(h for _, h in heads)
        last = {}
        for i, h in heads:
            last[h] = i
        lines = [ln for i, ln in enumerate(lines)
                 if not (re.match(r"^#{1,6}\s+", ln.strip())
                         and cnt[re.sub(r"[\s　]+", "", re.sub(r"^#{1,6}\s+", "", ln.strip()))] > 1
                         and i != last[re.sub(r"[\s　]+", "", re.sub(r"^#{1,6}\s+", "", ln.strip()))])]

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    parts = text.split("\n")
    if parts and parts[0].startswith("# "):
        parts[0] = f"# {title}"
    else:
        parts.insert(0, "")
        parts.insert(0, f"# {title}")
    return "\n".join(parts).strip() + "\n"


_CN = "零一二三四五六七八九"


def int2cn(n: int) -> str:
    if n <= 10:
        return "十" if n == 10 else _CN[n]
    if n < 20:
        return "十" + _CN[n % 10]
    if n < 100:
        return _CN[n // 10] + "十" + (_CN[n % 10] if n % 10 else "")
    return str(n)


def split_merged_articles(md: str) -> str:
    """有的 docx 把多条条文塞进同一段：按 第X条 的连续编号在行内补换行。

    只认同严格 1,2,3… 递增的编号，避免把条文中“本条例第三条”之类的
    引用误当成新条。
    """
    matches = list(re.finditer(r"第([一二三四五六七八九十百零〇两]+)条", md))
    expected = 1
    cuts: list[int] = []
    for m in matches:
        try:
            n = docx2md.cn2int(m.group(1))
        except ValueError:
            continue
        if n == expected:
            cuts.append(m.start())
            expected += 1
    if expected - 1 < 3:
        return md
    pieces = []
    last = 0
    for pos in cuts:
        seg = md[last:pos]
        if pos > 0 and md[pos - 1] != "\n":
            pieces.append(seg.rstrip() + "\n\n")
        else:
            pieces.append(seg)
        last = pos
    pieces.append(md[last:])
    text = "".join(pieces)
    return re.sub(r"\n{3,}", "\n\n", text)


def normalize_chapters(lines: list[str]) -> list[str]:
    """docx 中章标题被转成有序列表（"1. 总则"）时补成 "## 第一章 总则"。"""
    out = list(lines)
    for i, ln in enumerate(out):
        m = re.match(r"^(\d{1,2})\.\s+[\s　]*([\u4e00-\u9fa5]{1,6}(?:[\s　]*[\u4e00-\u9fa5]{1,6}){0,3})\s*$",
                     ln.strip())
        if not m:
            continue
        n = int(m.group(1))
        if not 1 <= n <= 40:
            continue
        nxt = [l.strip() for l in out[i + 1: i + 6] if l.strip()]
        if not nxt:
            continue
        if re.match(r"^第[一二三四五六七八九十百零〇两]+条", nxt[0]) or \
                re.match(r"^\d{1,2}\.\s+", nxt[0]):
            out[i] = f"## 第{int2cn(n)}章 {m.group(2)}"
    return out


def dates_from_md(md: str, fallback_prom: str, fallback_eff: str) -> tuple[str, str]:
    """从官方题注/正文提取公布日期与施行日期（flk 部分老文件缺 gbrq）。

    题注形如「（2002年4月25日…通过 2002年9月26日…批准）」，
    最后一个日期通常是批准/公布日期；「自XXXX年X月X日起施行」给施行日期。
    """
    head = md[:4000]
    m = re.search(r"[（(]([^（()）]{8,900}?)[）)]", head, re.S)
    block = m.group(1) if m else head
    ds = re.findall(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", block)
    prom = fallback_prom
    if ds:
        y, mo, d = ds[-1]
        prom = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    eff = fallback_eff
    if not eff:
        for pat in (r"自(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日起施行",
                    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:起)?施行"):
            mm = re.search(pat, head) or re.search(pat, md)
            if mm:
                y, mo, d = mm.groups()
                eff = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
                break
    return prom or fallback_prom, (eff or prom or fallback_eff)


def front_matter(meta: dict, articles: int, chars: int) -> str:
    status, code = STATUS.get(meta.get("sxx"), ("有效", 3))
    topics = ", ".join(meta["topics"])
    lines = [
        "---",
        f"id: flk-{meta['bbbs']}",
        f'title: {yq(meta["title"])}',
        f'short_title: {yq(meta["title"])}',
        "level: 地方性法规",
        "level_code: 5",
        f'issuer: {yq(meta["zdjgName"])}',
        'doc_number: ""',
        f"promulgated: {meta['promulgated']}",
        f"effective: {meta['effective']}",
        f"status: {status}",
        f"status_code: {code}",
        "category: 地方性法规",
        "doc_type: 地方性法规",
        f'province: {yq(meta["province"])}',
        f"topics: [{topics}]",
        f"source: https://flk.npc.gov.cn/detail?id={meta['bbbs']}",
        "source_name: 国家法律法规数据库",
        f"retrieved: {RETRIEVED}",
        'sha256: ""',
        f"chars: {chars}",
        f"articles: {articles}",
        f'version_group: {yq(meta["title"])}',
        'version_note: ""',
        "related: []",
        'notes: ""',
        "---",
        "",
    ]
    return "\n".join(lines)


def yq(s: str) -> str:
    s = str(s or "")
    if re.search(r"[:#\[\]{}&*!|>'\"%@`]", s) or s.strip() != s:
        return '"' + s.replace('"', '\\"') + '"'
    return s


def cmd_fetch(args) -> None:
    sel = json.loads((RESEARCH / "selected.json").read_text(encoding="utf-8"))
    sel.sort(key=lambda r: (r["province"] or "", r["title"]))
    if args.only:
        want = set(args.only.split(","))
        sel = [r for r in sel if r["bbbs"] in want]
    if args.limit:
        sel = sel[: args.limit]
    client = HttpClient(min_interval=args.interval, verbose=True)
    RAW.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    done_path = RESEARCH / "done.json"
    done: dict[str, str] = {}
    if done_path.exists():
        try:
            done = json.loads(done_path.read_text(encoding="utf-8"))
        except Exception:
            done = {}
    ok = skipped = 0
    failures: list[dict] = []
    t0 = time.time()
    for i, r in enumerate(sel, 1):
        bb = r["bbbs"]
        title = r["title"]
        rel = done.get(bb)
        if rel and (ROOT / rel).exists() and not getattr(args, "reconvert", False):
            skipped += 1
            continue
        try:
            # ---- 1. 元数据兜底：list 行缺日期/机关时查 detail
            if not r.get("gbrq") or not r.get("zdjgName"):
                d = client.get_json(
                    BASE + "/law-search/search/flfgDetails?"
                    + urllib.parse.urlencode({"bbbs": bb}))
                data = d.get("data") or {}
                r["gbrq"] = r.get("gbrq") or parse_ymd(data.get("gbrq"))
                r["sxrq"] = r.get("sxrq") or parse_ymd(data.get("sxrq"))
                r["zdjgName"] = r.get("zdjgName") or (data.get("zdjgName") or "").strip()
                if r.get("sxx") in (None, -1) and data.get("sxx") is not None:
                    r["sxx"] = int(data.get("sxx"))
                if not r.get("province"):
                    r["province"] = province_of(r)
            if not r.get("province"):
                raise FlkError("cannot determine province")
            # ---- 2. 下载 docx
            raw_path = RAW / f"{bb}.docx"
            client.download_docx(bb, raw_path)
            # ---- 3. docx -> md（老 .doc 用 LibreOffice 转 OOXML）
            src = docx_to_text(raw_path)
            md = docx2md.convert_docx(src, None, title=title)
            md = cleanup_md(md, title)
            md = split_merged_articles(md)
            md = "\n".join(normalize_chapters(md.split("\n")))
            md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
            arts = docx2md.extract_articles(md)
            if len(re.sub(r"\s", "", md)) < 90:
                raise FlkError("converted text too short")
            # ---- 4. 日期：list/detail 优先，缺失则从题注解析
            prom = r.get("gbrq") or ""
            eff = r.get("sxrq") or ""
            if not prom or not eff:
                prom2, eff2 = dates_from_md(md, prom, eff)
                prom = prom or prom2
                eff = eff or eff2
            if not prom:
                raise FlkError("no promulgated date (list/detail/题注 all empty)")
            notes = []
            if eff and prom and eff < prom:
                notes.append(f"经修正文本，原施行日期 {eff}")
                eff = prom
            if STATUS.get(r.get("sxx"), ("有效", 3))[0] == "已废止":
                notes.append("国家法律法规数据库标注为已废止")
            r["promulgated"] = prom
            r["effective"] = eff or prom
            r["notes"] = "；".join(notes)
            if not r.get("zdjgName"):
                raise FlkError("no issuer")
            # ---- 5. 写文件
            year = prom[:4]
            dest_dir = DATA / r["province"]
            dest_md = unique_dest(dest_dir / f"{safe_name(title)}-{year}.md", bb)
            chars = len(re.sub(r"\s", "", md))
            fm = front_matter(r, len(arts), chars)
            body = docx2md.strip_front_matter(md)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_md.write_text(fm + body, encoding="utf-8")
            done[bb] = str(dest_md.relative_to(ROOT))
            ok += 1
            print(f"[{i}/{len(sel)}] ok {r['province']} {title} ({len(arts)}条 "
                  f"{chars}字 {prom} {time.time()-t0:.0f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            failures.append({"bbbs": bb, "title": title,
                             "province": r.get("province"), "error": str(e)[:300]})
            print(f"[{i}/{len(sel)}] FAIL {title}: {e}", flush=True)
        if i % 10 == 0:
            done_path.write_text(json.dumps(done, ensure_ascii=False, indent=0),
                                 encoding="utf-8")
            (RESEARCH / "failures.json").write_text(
                json.dumps(failures, ensure_ascii=False, indent=1), encoding="utf-8")
    done_path.write_text(json.dumps(done, ensure_ascii=False, indent=0), encoding="utf-8")
    (RESEARCH / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: ok={ok} skipped={skipped} fail={len(failures)} "
          f"in {time.time()-t0:.0f}s; waf challenges={client.challenges} solved={client.solves}")


def cmd_safety(args) -> None:
    """按负责人要求追加 31 个省级行政区的「XX安全生产条例」（只收省级，市区级不收）。"""
    cand = json.loads((RESEARCH / "candidates.json").read_text(encoding="utf-8"))
    sel = json.loads((RESEARCH / "selected.json").read_text(encoding="utf-8"))
    have = {r["bbbs"] for r in sel}
    prov_names = list(PROVINCE_BY_CODE.values())
    byprov: dict[str, list[dict]] = {}
    for r in cand:
        t = r["title"].replace(" ", "")
        if not t.endswith("安全生产条例"):
            continue
        pref = t[: -len("安全生产条例")]
        if pref not in prov_names:
            continue
        byprov.setdefault(pref, []).append(r)
    added = 0
    picked = []
    for prov in prov_names:
        rows = byprov.get(prov) or []
        if not rows:
            continue
        # 优先现行有效(sxx=3)，其次按公布日期取最新
        rows.sort(key=lambda r: (0 if r.get("sxx") == 3 else 1, -(int((r.get("gbrq") or "0")[:4] or 0))))
        r = rows[0]
        if r["bbbs"] in have:
            continue
        r = dict(r)
        r["province"] = prov
        r["topics"] = ["劳动安全卫生"]
        r["reason"] = "provincial-safety"
        r["notes"] = "安全生产综合条例，与劳动安全卫生相关"
        sel.append(r)
        have.add(r["bbbs"])
        picked.append({"bbbs": r["bbbs"], "title": r["title"], "province": prov,
                       "promulgated": r.get("gbrq"), "sxx": r.get("sxx")})
        added += 1
    # 缺省级安全条例的省份：查经济特区法规(290)，如「海南经济特区安全生产条例」
    missing = [p for p in prov_names if p not in byprov]
    if missing:
        try:
            client = FlkClient(min_interval=args.interval, verbose=False)
            data = client.list_page(page=1, size=100, search_content="安全生产",
                                    search_type=1, codes=[290])
            for row in data.get("rows") or []:
                t = clean_title(row.get("title", "")).replace(" ", "")
                bb = row["bbbs"]
                if bb in have or not t.endswith("安全生产条例"):
                    continue
                prov = next((p for p in missing
                             if t.startswith(p) or t.startswith(re.sub(r"(省|市|自治区)$", "", p))),
                            None)
                if not prov:
                    continue
                r = {
                    "bbbs": bb, "title": t, "gbrq": parse_ymd(row.get("gbrq")),
                    "sxrq": parse_ymd(row.get("sxrq")), "sxx": row.get("sxx"),
                    "zdjgName": (row.get("zdjgName") or "").strip(),
                    "zdjgCodeId": row.get("zdjgCodeId"),
                    "flfgCodeId": row.get("flfgCodeId"), "kw": "安全生产",
                    "kw_all": ["安全生产"], "province": prov,
                    "topics": ["劳动安全卫生"], "reason": "provincial-safety-290",
                    "notes": "经济特区法规，按地方性法规归集；安全生产综合条例，与劳动安全卫生相关",
                }
                sel.append(r)
                have.add(bb)
                picked.append({"bbbs": bb, "title": t, "province": prov,
                               "promulgated": r["gbrq"], "sxx": r["sxx"]})
                added += 1
                missing = [p for p in missing if p != prov]
        except FlkError as e:
            print("  ! 经济特区法规补充查询失败:", e)
    # 每省只保留一条省级安全条例（优先现行有效版），并去掉重复 bbbs
    keep: dict[str, dict] = {}
    rest: list[dict] = []
    for r in sel:
        if str(r.get("reason", "")).startswith("provincial-safety"):
            pv = r.get("province") or ""
            cur = keep.get(pv)
            if cur is None or (0 if r.get("sxx") == 3 else 1) < (0 if cur.get("sxx") == 3 else 1):
                keep[pv] = r
            continue
        rest.append(r)
    seen_bb: set[str] = set()
    merged: list[dict] = []
    for r in rest + list(keep.values()):
        if r["bbbs"] in seen_bb:
            continue
        seen_bb.add(r["bbbs"])
        merged.append(r)
    sel = merged
    sel.sort(key=lambda r: (r["province"] or "", r["title"]))
    (RESEARCH / "selected.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    all_safety = [{"bbbs": r["bbbs"], "title": r["title"], "province": r["province"],
                   "promulgated": r.get("gbrq"), "sxx": r.get("sxx"), "notes": r.get("notes")}
                  for r in sel if str(r.get("reason", "")).startswith("provincial-safety")]
    all_safety.sort(key=lambda r: r["province"])
    (RESEARCH / "safety.json").write_text(json.dumps(all_safety, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"safety: added {added}; provinces covered {31 - len(missing)}/31; missing {missing}")
    print("bbbs:", ",".join(x["bbbs"] for x in picked))


# ------------------------------------------------------------------ phase: index
def cmd_index(args) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    rows = []
    for md in sorted(DATA.glob("*/*.md")):
        text = md.read_text(encoding="utf-8")
        fm = {}
        if text.startswith("---"):
            end = text.find("\n---", 3)
            block = text[3:end]
            for line in block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
        body = docx2md.strip_front_matter(text)
        arts = docx2md.extract_articles(body)
        rows.append({
            "title": fm.get("title", ""),
            "bbbs": fm.get("id", "").removeprefix("flk-"),
            "province": fm.get("province", ""),
            "issuer": fm.get("issuer", ""),
            "promulgated": fm.get("promulgated", ""),
            "effective": fm.get("effective", ""),
            "status": fm.get("status", ""),
            "source": fm.get("source", ""),
            "local_path": str(md.relative_to(ROOT)),
            "articles": len(arts),
            "chars": len(re.sub(r"\s", "", body)),
        })
    out = RESEARCH / "index.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"index: {len(rows)} files -> {out}")
    print("by province:", dict(sorted(Counter(r['province'] for r in rows).items())))
    zero = [r for r in rows if r["articles"] == 0]
    print(f"zero-article files: {len(zero)}")
    for r in zero[:10]:
        print("  ", r["title"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("--interval", type=float, default=1.35)
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--skip", action="append", default=[])
    s.set_defaults(func=cmd_sweep)
    f = sub.add_parser("filter")
    f.set_defaults(func=cmd_filter)
    d = sub.add_parser("fetch")
    d.add_argument("--interval", type=float, default=1.35)
    d.add_argument("--limit", type=int, default=0)
    d.add_argument("--only", default="")
    d.add_argument("--reconvert", action="store_true",
                   help="raw 已存在时也重新转换并覆盖 md（用于修正版式处理）")
    d.set_defaults(func=cmd_fetch)
    sf = sub.add_parser("safety")
    sf.add_argument("--interval", type=float, default=1.4)
    sf.set_defaults(func=cmd_safety)
    ix = sub.add_parser("index")
    ix.set_defaults(func=cmd_index)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
