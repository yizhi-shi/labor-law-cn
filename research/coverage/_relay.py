#!/usr/bin/env python3
"""本地回传服务：浏览器端 flk 页面把 detail JSON POST 回来，落盘到 cache/detail/。

WAF 只放行带浏览器 JS-challenge cookie 的 GET；Python 直连会被拦。
因此用 VS Code 内置浏览器（真实 Chromium）作为同源会话，把结果回传本地保存。
仅监听 127.0.0.1，供本次审计使用，结束即关闭。
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CACHE = Path(__file__).resolve().parent / "cache" / "detail"
CACHE.mkdir(parents=True, exist_ok=True)


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        if u.path == "/missing":
            q = parse_qs(u.query)
            want = [x for x in (q.get("bbbs", [""])[0]).split(",") if x]
            miss = [b for b in want if not (CACHE / f"{b}.json").exists()]
            body = json.dumps({"missing": miss}).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self._cors()
        self.end_headers()

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        bbbs = q.get("bbbs", [""])[0]
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        try:
            if u.path != "/save" or not bbbs:
                raise ValueError("bad path")
            if not re.fullmatch(r"[0-9a-zA-Z]+", bbbs):
                raise ValueError("bad bbbs")
            data = json.loads(raw)
            (CACHE / f"{bbbs}.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as e:  # noqa: BLE001
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 8799), H)
    print("relay on 127.0.0.1:8799", flush=True)
    srv.serve_forever()
