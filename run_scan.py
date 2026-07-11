#!/usr/bin/env python3
"""
daddy-screener — entrypoint
สแกน 1 universe → เขียนผลลง docs/<universe>.json (GitHub Pages เสิร์ฟไฟล์นี้)

Usage:
    python run_scan.py --universe nasdaq100
    python run_scan.py --universe sp500 --limit 50 --throttle 0.3

ไม่ใช้ FMP / Supabase — Yahoo ฟรีล้วน · $0
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from screener.fetch_yahoo import fetch_daily, resample, MIN_CANDLES
from screener.scoring import evaluate, INDEX_FOR
from screener.patterns import detect_reversals

# เรดาร์กลับตัว (W3-11 P3) — จัดกลุ่ม pattern เป็น "ก่อยอด" / "ก่อฐาน"
REVERSAL_GROUP = {
    "double_top": "top", "head_shoulders": "top",
    "double_bottom": "bottom", "inv_head_shoulders": "bottom",
}
# เอาเฉพาะ forming + confirmed (D-RR-2) — ตัด failed ทิ้ง
REVERSAL_STATUS = ("forming", "confirmed")


def collect_reversals(symbol, weekly, monthly):
    """ต่อท้าย scan (0 fetch เพิ่ม): reuse weekly/monthly → คืน list rows กลับตัว
    ต่อ TF เอา pattern ที่ชัดสุดของแต่ละกลุ่ม (top/bottom) กันซ้ำรก"""
    rows = []
    for tf, candles in (("W", weekly), ("M", monthly)):
        res = detect_reversals(candles, tf)
        if not res["enough"]:
            continue
        for p in res["patterns"]:
            if p["status"] not in REVERSAL_STATUS:
                continue
            grp = REVERSAL_GROUP.get(p["key"])
            if not grp:
                continue
            rows.append({
                "symbol": symbol, "tf": tf, "key": p["key"], "group": grp,
                "bias": p["bias"], "status": p["status"],
                "confidence": p["confidence"], "volConfirmed": p["volConfirmed"],
            })
    return rows

ROOT = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_DIR = os.path.join(ROOT, "screener", "universes")
DOCS_DIR = os.path.join(ROOT, "docs")


def load_universe(name):
    path = os.path.join(UNIVERSE_DIR, f"{name}.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # รองรับทั้ง ["AAPL",...] และ [{"symbol":"AAPL","sector":"Tech"},...]
    out = []
    for item in data.get("symbols", data if isinstance(data, list) else []):
        if isinstance(item, str):
            out.append({"symbol": item, "sector": None})
        elif isinstance(item, dict) and item.get("symbol"):
            out.append({"symbol": item["symbol"], "sector": item.get("sector")})
    return out


def fetch_index_weekly(universe):
    idx = INDEX_FOR.get(universe)
    if not idx:
        return []
    daily = fetch_daily(idx, rng="5y")
    return resample(daily, "1wk") if daily else []


def scan(universe, limit=None, throttle=0.25):
    symbols = load_universe(universe)
    if limit:
        symbols = symbols[:limit]
    total = len(symbols)
    print(f"[scan] {universe} — {total} symbols — {datetime.now(timezone.utc).isoformat()}")

    index_weekly = fetch_index_weekly(universe)
    if not index_weekly:
        print(f"[scan] WARN: no index candles for {universe} (RS จะเป็น null)")

    results = []
    reversals = []
    for i, item in enumerate(symbols):
        symbol = item["symbol"]
        print(f"[scan] {i+1}/{total} {symbol}", end=" ", flush=True)
        try:
            daily = fetch_daily(symbol, rng="5y")
            if len(daily) < MIN_CANDLES["1d"]:
                print(f"→ skip ({len(daily)} daily)")
                time.sleep(throttle)
                continue
            weekly = resample(daily, "1wk")
            monthly = resample(daily, "1mo")
            row = evaluate(symbol, daily, weekly, monthly, index_weekly,
                           universe, sector=item.get("sector"))
            rev = collect_reversals(symbol, weekly, monthly)  # 0 fetch เพิ่ม (reuse candles)
            reversals.extend(rev)
            if row:
                results.append(row)
                print(f"→ ✅ {row['grade']} {row['score']} ({row['signal'] or '—'})"
                      + (f" · 🔄{len(rev)}" if rev else ""))
            else:
                print("→ —" + (f" · 🔄{len(rev)}" if rev else ""))
        except Exception as e:  # noqa: BLE001
            print(f"→ ⚠️ {e}")
        time.sleep(throttle)

    results.sort(key=lambda r: r["score"], reverse=True)
    write_output(universe, results, total)
    write_reversals(universe, reversals, total)
    return results


def write_output(universe, results, scanned):
    os.makedirs(DOCS_DIR, exist_ok=True)
    grade_a = sum(1 for r in results if r["grade"] == "A")
    grade_b = sum(1 for r in results if r["grade"] == "B")
    payload = {
        "schema_version": 1,
        "universe": universe,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {"scanned": scanned, "passed_gates": len(results),
                  "grade_a": grade_a, "grade_b": grade_b},
        "results": results,
    }
    path = os.path.join(DOCS_DIR, f"{universe}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[scan] wrote {path} — {len(results)} setups (A={grade_a} B={grade_b})")


def write_reversals(universe, reversals, scanned):
    """เขียน docs/<universe>-reversals.json (เรดาร์กลับตัว W3-11 P3)
    เรียงตามความชัด (confirmed ก่อน forming · confidence สูงก่อน) — frontend ตัด cap/gate เอง"""
    os.makedirs(DOCS_DIR, exist_ok=True)
    status_rank = {"confirmed": 0, "forming": 1}
    reversals.sort(key=lambda r: (status_rank.get(r["status"], 2), -r["confidence"]))
    tops = sum(1 for r in reversals if r["group"] == "top")
    bottoms = sum(1 for r in reversals if r["group"] == "bottom")
    payload = {
        "schema_version": 1,
        "universe": universe,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {"scanned": scanned, "found": len(reversals),
                  "tops": tops, "bottoms": bottoms},
        "results": reversals,
    }
    path = os.path.join(DOCS_DIR, f"{universe}-reversals.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[scan] wrote {path} — {len(reversals)} reversals (top={tops} bottom={bottoms})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True,
                    choices=["nasdaq100", "sp500", "sp400", "sp600"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--throttle", type=float, default=0.25)
    args = ap.parse_args()
    scan(args.universe, limit=args.limit, throttle=args.throttle)


if __name__ == "__main__":
    sys.exit(main())
