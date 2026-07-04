#!/usr/bin/env python3
"""
รีเฟรชรายชื่อหุ้นของแต่ละ universe (เดือนละครั้งพอ) — $0 ไม่ใช้ FMP
  S&P500      → Wikipedia constituents table
  Russell2000 → iShares IWM holdings CSV (public)
  NASDAQ100   → ไม่แตะ (hardcode ใน nasdaq100.json — เสถียร)

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

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
IWM_CSV_URL = ("https://www.ishares.com/us/products/239710/"
               "ishares-russell-2000-etf/1467271812596.ajax"
               "?fileType=csv&fileName=IWM_holdings&dataType=fund")


def _get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


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
    csv_text = _get(IWM_CSV_URL)
    # ไฟล์ iShares มี header meta หลายบรรทัดก่อน table จริง → หา header row ที่มี "Ticker"
    lines = csv_text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.lower().startswith('"ticker"') or ln.lower().startswith("ticker")), None)
    if start is None:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    out = []
    for row in reader:
        tk = (row.get("Ticker") or "").strip().strip('"')
        asset = (row.get("Asset Class") or "").strip().strip('"')
        if not tk or tk == "-":
            continue
        if asset and asset.lower() not in ("equity",):
            continue
        if re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", tk):
            out.append({"symbol": tk.replace(".", "-"), "sector": None})
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
    floor = {"sp500": 400, "russell2000": 1000}[name]
    if got < floor:
        print(f"[universe] SKIP {name}: got {got} < {floor} (คงไฟล์เดิม กันทับของพัง)")
        return False
    return True


def main():
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
