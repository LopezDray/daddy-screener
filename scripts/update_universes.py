#!/usr/bin/env python3
"""
รีเฟรชรายชื่อหุ้นของแต่ละ universe (เดือนละครั้ง + trigger มือได้ตอนมี ad-hoc change) — $0 ไม่ใช้ FMP
  NASDAQ100   → Wikipedia Nasdaq-100 components (เปลี่ยนกลางปีได้ ad-hoc → ต้อง auto)
  S&P500      → Wikipedia constituents table
  Russell2000 → iShares IWM holdings CSV (public)

Guard: ถ้า fetch/parse ได้จำนวนน้อยผิดปกติ → คงไฟล์เดิมไว้ (ไม่ทับด้วยของพัง)
"""

import csv
import io
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_DIR = os.path.join(ROOT, "screener", "universes")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; daddy-screener/1.0)"}

NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
IWM_CSV_URL = ("https://www.ishares.com/us/products/239710/"
               "ishares-russell-2000-etf/1467271812596.ajax"
               "?fileType=csv&fileName=IWM_holdings&dataType=fund")


BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _get(url, ua=None):
    headers = dict(HEADERS)
    if ua:
        headers["User-Agent"] = ua
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")  # utf-8-sig = strip BOM


def fetch_nasdaq100():
    """ดึง NASDAQ-100 components จาก Wikipedia — header-aware (หาคอลัมน์ Ticker เอง)"""
    html = _get(NASDAQ100_URL)
    tables = re.findall(r"<table[^>]*wikitable[^>]*>.*?</table>", html, re.S)
    best = []
    for table in tables:
        rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)
        if not rows:
            continue
        header = [re.sub(r"<[^>]+>", "", h).strip().lower()
                  for h in re.findall(r"<th.*?>(.*?)</th>", rows[0], re.S)]
        tcol = next((i for i, h in enumerate(header) if "ticker" in h or "symbol" in h), None)
        if tcol is None:
            continue
        out = []
        for r in rows[1:]:
            cells = re.findall(r"<t[dh].*?>(.*?)</t[dh]>", r, re.S)
            if len(cells) <= tcol:
                continue
            raw = re.sub(r"<[^>]+>", "", cells[tcol]).strip().replace("&amp;", "&")
            if re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", raw):
                out.append({"symbol": raw.replace(".", "-"), "sector": None})
        if len(out) > len(best):
            best = out            # เลือกตารางที่ได้ ticker เยอะสุด (= components table)
    return _dedupe(best)


def fetch_sp500():
    html = _get(SP500_URL)
    # ตัดเอาเฉพาะตาราง constituents ตัวแรก แล้วดึง ticker จากคอลัมน์แรกของแต่ละแถว
    m = re.search(r'id="constituents".*?</table>', html, re.S)
    table = m.group(0) if m else html
    rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)
    out = []
    for r in rows:
        cells = re.findall(r"<td.*?>(.*?)</td>", r, re.S)
        if not cells:
            continue
        # ticker อยู่ใน cell แรก อาจห่อด้วย <a>
        raw = re.sub(r"<[^>]+>", "", cells[0]).strip()
        raw = raw.replace("&amp;", "&")
        if re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", raw):
            out.append({"symbol": raw.replace(".", "-"), "sector": None})  # BRK.B → BRK-B (Yahoo)
    # sector: คอลัมน์ GICS Sector (index 2) ถ้ามี
    return _dedupe(out)


def fetch_russell2000():
    # iShares บล็อก bot UA บ่อย → ใช้ browser UA เต็ม · BOM ถูก strip ใน _get แล้ว
    csv_text = _get(IWM_CSV_URL, ua=BROWSER_UA)
    lines = csv_text.splitlines()
    # หา header row: บรรทัดที่มี field ชื่อ "ticker" (ยืดหยุ่น — มี/ไม่มี quote, อยู่คอลัมน์ไหนก็ได้)
    hdr_idx = None
    for i, ln in enumerate(lines):
        fields = [c.strip().strip('"').lower() for c in ln.split(",")]
        if "ticker" in fields:
            hdr_idx = i
            break
    if hdr_idx is None:
        # debug: log ให้รอบหน้าเห็นว่า iShares ตอบอะไรมา (HTML block? empty?)
        print(f"[universe] russell2000 debug: no 'ticker' header · bytes={len(csv_text)} · "
              f"first160={csv_text[:160]!r}")
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines[hdr_idx:])))
    out = []
    for row in reader:
        tk = (row.get("Ticker") or row.get("ticker") or "").strip().strip('"')
        asset = (row.get("Asset Class") or "").strip().strip('"')
        if not tk or tk == "-":
            continue
        if asset and asset.lower() != "equity":     # ตัด cash/derivative
            continue
        if re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", tk):
            out.append({"symbol": tk.replace(".", "-"), "sector": None})
    print(f"[universe] russell2000 debug: header@line{hdr_idx} · parsed={len(out)} tickers")
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


def _min_ok(name, got):
    floor = {"nasdaq100": 90, "sp500": 400, "russell2000": 1000}[name]
    if got < floor:
        print(f"[universe] SKIP {name}: got {got} < {floor} (คงไฟล์เดิม กันทับของพัง)")
        return False
    return True


def main():
    try:
        nd = fetch_nasdaq100()
        if _min_ok("nasdaq100", len(nd)):
            _write("nasdaq100", nd)
    except Exception as e:  # noqa: BLE001
        print(f"[universe] nasdaq100 error: {e}")

    try:
        sp = fetch_sp500()
        if _min_ok("sp500", len(sp)):
            _write("sp500", sp)
    except Exception as e:  # noqa: BLE001
        print(f"[universe] sp500 error: {e}")

    try:
        ru = fetch_russell2000()
        if _min_ok("russell2000", len(ru)):
            _write("russell2000", ru)
    except Exception as e:  # noqa: BLE001
        print(f"[universe] russell2000 error: {e}")


if __name__ == "__main__":
    main()
