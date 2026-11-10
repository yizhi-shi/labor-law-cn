"""Smoke tests for the labor-law-cn corpus and CLI.

Run with:  python3 -m pytest -q   (or)   python3 tests/test_smoke.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INDEX = DATA / "index.json"


def load_index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8"))


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def test_index_exists_and_min_count():
    idx = load_index()
    assert idx["meta"]["count"] >= 200
    assert len(idx["documents"]) == idx["meta"]["count"]


def test_required_front_matter_fields():
    required = {"id", "title", "level", "issuer", "promulgated", "effective",
                "status", "topics", "source", "path", "sha256", "articles"}
    for doc in load_index()["documents"]:
        missing = required - set(doc)
        assert not missing, f"{doc.get('title')} missing {missing}"
        assert doc["status"] in ("有效", "已修改", "已废止", "尚未生效")


def test_core_statutes_present_and_effective():
    docs = load_index()["documents"]
    titles = {d["title"] for d in docs if d["status"] in ("有效", "尚未生效")}
    for title in ("中华人民共和国劳动法", "中华人民共和国劳动合同法",
                  "中华人民共和国社会保险法", "工伤保险条例",
                  "中华人民共和国劳动争议调解仲裁法"):
        assert title in titles, f"missing core statute: {title}"


def test_search_returns_relevant_statute():
    r = run("scripts/search.py", "加班费", "--status", "有效", "--limit", "5")
    assert r.returncode == 0, r.stderr
    assert "劳动合同法" in r.stdout or "劳动法" in r.stdout
    assert "加班费" in r.stdout


def test_article_lookup():
    r = run("scripts/search.py", "--doc", "劳动合同法", "--article", "82")
    assert r.returncode == 0, r.stderr
    assert "二倍" in r.stdout


def test_age_filter():
    r = run("scripts/search.py", "--list", "--age", "超龄")
    assert r.returncode == 0, r.stderr
    assert "超龄" in r.stdout


def test_province_filter():
    r = run("scripts/search.py", "--list", "--province", "北京市", "--limit", "3")
    assert r.returncode == 0, r.stderr


def test_json_output_is_valid():
    r = run("scripts/search.py", "工伤", "--json", "--limit", "3")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert isinstance(payload, list) and payload
    assert "source" in payload[0]


def test_sha256_matches_body():
    import hashlib
    docs = load_index()["documents"]
    for doc in docs[:10]:
        text = (ROOT / doc["path"]).read_text(encoding="utf-8")
        body = text[text.find("\n---", 3) + 4:].lstrip("\n")
        assert hashlib.sha256(body.encode()).hexdigest() == doc["sha256"]


def test_verify_script_passes():
    r = run("scripts/verify.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
