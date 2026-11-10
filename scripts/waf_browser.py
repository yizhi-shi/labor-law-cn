#!/usr/bin/env python3
"""Solve the flk.npc.gov.cn WAF JS challenge with headless Chrome and export cookies.

The site's WAF (WZWS) hands out an HTML challenge that computes a signed cookie
in JavaScript.  Plain HTTP clients get the challenge again and again, so we let
a real Chrome pass it once and then reuse the resulting cookies from Python.

Usage:
    python3 scripts/waf_browser.py            # refresh cookie cache
    cookies = load_cookies()                  # -> list[dict]
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client

TARGET = "https://flk.npc.gov.cn/law-search/search/flfgDetails?bbbs=ff8080816f135f46016f20f16ee11737"
CACHE = Path.home() / ".cache" / "flk-waf-cookies.json"
PROFILE = Path(tempfile.gettempdir()) / "flk-chrome-profile"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_json(url: str, timeout: float = 15.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"chrome debug endpoint not ready: {url}")


def refresh(timeout: float = 25.0) -> list[dict]:
    if PROFILE.exists():
        shutil.rmtree(PROFILE, ignore_errors=True)
    PROFILE.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"
    proc = subprocess.Popen(
        [chrome, "--headless=new", f"--remote-debugging-port={port}",
         f"--user-data-dir={PROFILE}", "--no-sandbox", "--disable-gpu",
         "--disable-dev-shm-usage", f"--user-agent={UA}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_json(f"http://127.0.0.1:{port}/json/version")
        # create a fresh tab
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
        try:
            tab = json.loads(urllib.request.urlopen(req, timeout=5).read())
        except Exception:
            tab = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/new?about:blank", timeout=5).read())
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=10,
                                         suppress_origin=True)
        mid = 0

        def send(method, params=None, wait=True):
            nonlocal mid
            mid += 1
            ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            if not wait:
                return None
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == mid:
                    return msg

        send("Network.enable")
        send("Page.enable")
        send("Page.navigate", {"url": TARGET})
        # wait until the page body is the JSON payload (challenge solved) or timeout
        body = ""
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(1.5)
            r = send("Runtime.evaluate", {"expression": "document.body?document.body.innerText.slice(0,80):''", "returnByValue": True})
            body = (((r or {}).get("result") or {}).get("result") or {}).get("value") or ""
            if body.strip().startswith("{"):
                break
        cookies = send("Network.getAllCookies").get("result", {}).get("cookies", [])
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"cookies": cookies, "saved_at": time.time(),
                                     "body_head": body[:200]}, ensure_ascii=False), encoding="utf-8")
        ws.close()
        return cookies
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def load_cookies(max_age: float = 3600) -> dict[str, str]:
    data = json.loads(CACHE.read_text(encoding="utf-8"))
    if time.time() - data.get("saved_at", 0) > max_age:
        refresh()
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    return {c["name"]: c["value"] for c in data.get("cookies", [])
            if "flk.npc.gov.cn" in c.get("domain", "")}


if __name__ == "__main__":
    cs = refresh()
    print(f"got {len(cs)} cookies")
    for c in cs:
        if "flk" in c.get("domain", ""):
            print(c["name"], c["value"][:40])
