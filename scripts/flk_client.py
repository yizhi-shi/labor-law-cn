#!/usr/bin/env python3
"""Client for 国家法律法规数据库 (flk.npc.gov.cn).

Only official, unauthenticated endpoints are used:

  POST /law-search/search/list          检索（分页）
  GET  /law-search/search/flfgDetails   法规详情（元数据 + 目录树 + OSS 文件路径）
  GET  /law-search/download/mobile      302 到 OBS 签名地址（format=docx|pdf）

The site is protected by a WAF that occasionally answers with HTML instead of
JSON.  Every request therefore goes through `_request()` which retries with
exponential backoff and re-primes the session cookie when needed.
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "https://flk.npc.gov.cn"
LIST_URL = BASE + "/law-search/search/list"
DETAIL_URL = BASE + "/law-search/search/flfgDetails"
DOWNLOAD_URL = BASE + "/law-search/download/mobile"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

# 时效性 sxx
SXX = {1: "已废止", 2: "已修改", 3: "有效", 4: "尚未生效"}

# 法律法规分类（flfgCodeId）
LEVELS = {
    "法律": [110, 120, 130, 140, 150, 155, 160, 170],  # 宪法相关法…诉讼与非诉讼程序法
    "法律解释": [180],
    "有关法律问题和重大问题的决定": [190],
    "行政法规": [210],
    "监察法规": [220],
    "地方性法规": [230],
    "自治条例": [260],
    "单行条例": [270],
    "经济特区法规": [290],
    "司法解释": [320, 330, 340],
}


class FlkError(RuntimeError):
    pass


class FlkClient:
    def __init__(self, min_interval: float = 1.2, timeout: int = 45, verbose: bool = False):
        self.min_interval = min_interval
        self.timeout = timeout
        self.verbose = verbose
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj)
        )
        self._last = 0.0
        self._primed = False
        self.request_count = 0

    # ---------------------------------------------------------------- plumbing
    def _sleep(self) -> None:
        dt = time.time() - self._last
        wait = self.min_interval + random.uniform(0, 0.25) - dt
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _prime(self) -> None:
        """Visit the homepage once so the WAF hands out its session cookie."""
        if self._primed:
            return
        try:
            req = urllib.request.Request(
                BASE + "/", headers={"User-Agent": UA, "Accept": "text/html"}
            )
            with self.opener.open(req, timeout=self.timeout) as r:
                r.read(4096)
        except Exception:
            pass
        self._primed = True

    def _solve_waf(self, html: bytes) -> bool:
        """Run scripts/waf_solver.js on a WZWS challenge page, then hit the pass URL."""
        solver = Path(__file__).resolve().parent / "waf_solver.js"
        if not solver.exists():
            return False
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("wb", suffix=".html", delete=False) as f:
                f.write(html)
                tmp = f.name
            r = subprocess.run(["node", str(solver), tmp, "--raw"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return False
            pass_url = (r.stdout or "").strip().splitlines()[-1]
            if not pass_url.startswith("/"):
                return False
            req = urllib.request.Request(BASE + pass_url,
                                         headers={"User-Agent": UA, "Referer": BASE + "/"})
            with self.opener.open(req, timeout=self.timeout) as resp:
                resp.read(2048)
            if self.verbose:
                print("  ~ WAF challenge solved via node waf_solver.js")
            return True
        except Exception as e:
            if self.verbose:
                print(f"  ~ WAF solver failed: {e}")
            return False
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def _request(self, url: str, data: dict | None = None, tries: int = 6):
        self._prime()
        body = json.dumps(data).encode() if data is not None else None
        last_err: Exception | None = None
        for attempt in range(tries):
            self._sleep()
            try:
                req = urllib.request.Request(url, data=body)
                req.add_header("User-Agent", UA)
                req.add_header("Accept", "application/json, text/plain, */*")
                req.add_header("Referer", BASE + "/search")
                if body is not None:
                    req.add_header("Content-Type", "application/json;charset=UTF-8")
                with self.opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    ctype = resp.headers.get("Content-Type", "")
                    self.request_count += 1
                    if "json" not in ctype and raw[:1] not in (b"{", b"["):
                        if self._solve_waf(raw):
                            raise FlkError("waf-challenge-solved")
                        snippet = raw[:200].decode("utf-8", "ignore")
                        raise FlkError(
                            f"non-JSON response ({ctype}, {len(raw)} bytes) for {url}: {snippet!r}"
                        )
                    return raw
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, FlkError) as e:
                last_err = e
                if self.verbose:
                    print(f"  ! retry {attempt + 1}/{tries} {url}: {e}")
                self._primed = False
                msg = str(e)
                if "waf-challenge-solved" in msg:
                    time.sleep(0.5)
                elif "non-JSON" in msg or "Please enable JavaScript" in msg or "WZWS" in msg:
                    # WAF rate-limit challenge: the IP is cooling down.  Wait long.
                    cool = 90 + 45 * attempt
                    if self.verbose:
                        print(f"  ~ WAF challenge detected, cooling down {cool}s")
                    time.sleep(cool)
                else:
                    time.sleep(min(30, 2.0 * (attempt + 1)) + random.uniform(0, 1))
        raise FlkError(f"request failed after {tries} tries: {url}: {last_err}")

    # -------------------------------------------------------------------- api
    def list_page(
        self,
        page: int = 1,
        size: int = 100,
        search_content: str = "",
        search_type: int = 1,
        codes: list[int] | None = None,
        sxx: list[int] | None = None,
        **extra,
    ) -> dict:
        payload = {
            "searchRange": 1,
            "searchType": search_type,
            "searchContent": search_content,
            "sxx": sxx or [],
            "flfgCodeId": codes or [],
            "zdjgCodeId": [],
            "sxrq": [],
            "gbrq": [],
            "pageNum": page,
            "pageSize": size,
        }
        payload.update(extra)
        raw = self._request(LIST_URL, payload)
        return json.loads(raw)

    def iter_list(self, **kwargs):
        """Yield every row for a query, paging through results."""
        page = 1
        seen: set[str] = set()
        while True:
            data = self.list_page(page=page, **kwargs)
            rows = data.get("rows") or []
            for row in rows:
                if row["bbbs"] not in seen:
                    seen.add(row["bbbs"])
                    yield row
            total = data.get("total") or 0
            if len(rows) < kwargs.get("size", 100) or page * kwargs.get("size", 100) >= total:
                break
            page += 1

    def list_all(self, **kwargs) -> list[dict]:
        return list(self.iter_list(**kwargs))

    def detail(self, bbbs: str) -> dict:
        url = DETAIL_URL + "?" + urllib.parse.urlencode({"bbbs": bbbs})
        raw = self._request(url)
        data = json.loads(raw)
        if data.get("code") != 200 or not data.get("data"):
            raise FlkError(f"detail failed for {bbbs}: {data.get('msg')}")
        return data["data"]

    def download_url(self, bbbs: str, fmt: str = "docx", file_id: str = "") -> str:
        q = urllib.parse.urlencode({"format": fmt, "bbbs": bbbs, "fileId": file_id})
        # download/mobile answers 302 -> signed OBS URL; do not auto-follow here
        req = urllib.request.Request(
            DOWNLOAD_URL + "?" + q,
            headers={"User-Agent": UA, "Referer": BASE + "/detail"},
        )
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        no_redirect = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPCookieProcessor(self.cj)
        )
        self._sleep()
        try:
            with no_redirect.open(req, timeout=self.timeout) as r:
                return r.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                return e.headers["Location"]
            raise

    def download(self, bbbs: str, dest: str | Path, fmt: str = "docx", file_id: str = "") -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 1024:
            return dest
        url = self.download_url(bbbs, fmt, file_id)
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    blob = r.read()
                if len(blob) < 512:
                    raise FlkError(f"downloaded file too small: {len(blob)}")
                dest.write_bytes(blob)
                return dest
            except Exception as e:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        return dest


def clean_title(t: str) -> str:
    """Strip search-result <em> highlights."""
    return re.sub(r"<[^>]+>", "", t or "").strip()
