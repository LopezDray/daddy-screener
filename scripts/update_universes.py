#!/usr/bin/env python3
"""
รีเฟรชรายชื่อหุ้นของแต่ละ universe (เดือนละครั้ง + trigger มือได้ตอนมี ad-hoc change) — $0 ไม่ใช้ FMP
ทุก universe ดึงจาก Wikipedia (reliable, ไม่โดน datacenter-IP block เหมือน iShares)
  NASDAQ100 → Wikipedia Nasdaq-100 components (large/growth)
  S&P 500   → large cap  | S&P 400 → mid cap | S&P 600 → small cap
  (S&P 500+400+600 = S&P Composite 1500 = คลุมตลาดสหรัฐแบบคัดกรอง)

Guard: ถ้า fetch/parse ได้จำนวนน้อยผิดปกติ → คงไฟล์เดิมไว้ (ไม่ทับด้วยของพัง)
"""

import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_DIR = os.path.join(ROOT, "screener", "universes")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; daddy-screener/1.0)"}

NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
SP_URLS = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}
FLOORS = {"nasdaq100": 90, "sp500": 400, "sp400": 300, "sp600": 450}


def _get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")  # utf-8-sig = strip BOM


def _cells(row):
    return re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)


def _text(cell):
    return re.sub(r"<[^>]+>", "", cell).strip().replace("&amp;", "&")


def _is_ticker(s):
    return bool(re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", s))


def fetch_nasdaq100():
    """Wikipedia Nasdaq-100 — ทน <tr class=...>, header-aware + column-scan fallback, เลือกตาราง ~100"""
    html = _get(NASDAQ100_URL)
    tables = re.findall(r"<table[^>]*wikitable[^>]*>.*?</table>", html, re.S)
    picks = []
    for table in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
        if len(rows) < 50:
            continue
        header = [_text(h).lower() for h in _cells(rows[0])]
        tcol = next((i for i, h in enumerate(header) if "ticker" in h or "symbol" in h), None)
        out = []
        for r in rows[1:]:
            cells = _cells(r)
            if not cells:
                continue
            scan = [cells[tcol]] if (tcol is not None and len(cells) > tcol) else cells
            for cell in scan:
                raw = _text(cell)
                if _is_ticker(raw):
                    out.append({"symbol": raw.replace(".", "-"), "sector": None})
                    break
        if out:
            picks.append(_dedupe(out))
    # NASDAQ-100 มี ~101 หลักทรัพย์ → เลือกตารางที่ count ∈ [90,120] (กันตาราง "การเปลี่ยนแปลง" ที่ยาวกว่า)
    in_band = [p for p in picks if 90 <= len(p) <= 120]
    best = max(in_band, key=len) if in_band else []
    if not best:
        print(f"[universe] nasdaq100 debug: no ~100 table · counts={[len(p) for p in picks]}")
    return best


def fetch_sp_index(name):
    """generic S&P constituents (500/400/600) — ตาราง id=constituents, header-aware หา symbol column"""
    html = _get(SP_URLS[name])
    m = re.search(r'id="constituents".*?</table>', html, re.S)
    table = m.group(0) if m else html
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
    if not rows:
        return []
    header = [_text(h).lower() for h in _cells(rows[0])]
    scol = next((i for i, h in enumerate(header) if "symbol" in h or "ticker" in h), 0)
    out = []
    for r in rows[1:]:
        cells = _cells(r)
        if len(cells) <= scol:
            continue
        raw = _text(cells[scol])
        if _is_ticker(raw):
            out.append({"symbol": raw.replace(".", "-"), "sector": None})  # BRK.B → BRK-B (Yahoo)
    return _dedupe(out)


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        if it["symbol"] not in seen:
            seen.add(it["symbol"])
            out.append(it)
    return out


def _write(name, symbols):
    path = os.path.join(UNIVERSE_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"universe": name, "count": len(symbols), "symbols": symbols},
                  f, ensure_ascii=False, indent=1)
    print(f"[universe] wrote {name}: {len(symbols)} symbols")


def _refresh(name, fetcher):
    try:
        syms = fetcher()
        if len(syms) < FLOORS[name]:
            print(f"[universe] SKIP {name}: got {len(syms)} < {FLOORS[name]} (คงไฟล์เดิม กันทับของพัง)")
            return
        _write(name, syms)
    except Exception as e:  # noqa: BLE001
        print(f"[universe] {name} error: {e}")


def main():
    _refresh("nasdaq100", fetch_nasdaq100)
    for name in ("sp500", "sp400", "sp600"):
        _refresh(name, lambda n=name: fetch_sp_index(n))


if __name__ == "__main__":
    main()
