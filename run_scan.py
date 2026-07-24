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
import random
import sys
import time
from datetime import datetime, timezone
from statistics import mean

from screener.fetch_yahoo import fetch_daily, resample, MIN_CANDLES, congestion_penalty
from screener.scoring import evaluate, INDEX_FOR
from screener.patterns import detect_reversals
from screener.stage import analyze_stage, MA_PERIOD
from screener.levels import build_levels_row

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


def scan(universe, limit=None, throttle=0.25, shard=None):
    symbols = load_universe(universe)
    if shard is not None:
        k, n = shard
        symbols = symbols[k::n]          # interleave stripe → เฉลี่ย liquidity/ตัวอักษรทุก shard
    if limit:
        symbols = symbols[:limit]
    total = len(symbols)
    tag = f"{universe}" + (f" shard{shard[0]}/{shard[1]}" if shard is not None else "")
    print(f"[scan] {tag} — {total} symbols — {datetime.now(timezone.utc).isoformat()}")

    index_weekly = fetch_index_weekly(universe)
    if not index_weekly:
        print(f"[scan] WARN: no index candles for {universe} (RS จะเป็น null)")

    build_table = (universe == "us-all")   # master quant table เฉพาะ us-all (parity 4 universe เดิม)
    results = []
    reversals = []
    levels = []
    table = []
    for i, item in enumerate(symbols):
        symbol = item["symbol"]
        print(f"[scan] {i+1}/{total} {symbol}", end=" ", flush=True)
        try:
            daily = fetch_daily(symbol, rng="5y")
            if len(daily) < MIN_CANDLES["1d"]:
                print(f"→ skip ({len(daily)} daily)")
                time.sleep(_pace(throttle))
                continue
            weekly = resample(daily, "1wk")
            monthly = resample(daily, "1mo")
            row = evaluate(symbol, daily, weekly, monthly, index_weekly,
                           universe, sector=item.get("sector"))
            rev = collect_reversals(symbol, weekly, monthly)  # 0 fetch เพิ่ม (reuse candles)
            reversals.extend(rev)
            # proximity levels — คำนวณ "ทุกตัว" ไม่ใช่แค่ที่ผ่าน gate breakout (0 fetch เพิ่ม)
            wa = analyze_stage(weekly, MA_PERIOD["1wk"], "1wk")
            lv = build_levels_row(
                symbol, daily, sector=item.get("sector"),
                w_stage=(wa["stage"] if wa else None),
                setup=(row["setup"] if row else None),
                signal=(row["signal"] if row else None),
                reversal_rows=rev)
            if lv:
                levels.append(lv)
            if build_table:                # แถว quant สำหรับ "ทุกตัว" (ไม่ผ่าน gate ก็ยังลง table)
                trow = build_table_row(symbol, daily, weekly, monthly, wa, row, lv, rev)
                if trow:
                    table.append(trow)
            if row:
                results.append(row)
                print(f"→ ✅ {row['grade']} {row['score']} ({row['signal'] or '—'})"
                      + (f" · 🔄{len(rev)}" if rev else "")
                      + (f" · 🎯{lv['nearest']['level']}" if lv else ""))
            else:
                print("→ —" + (f" · 🔄{len(rev)}" if rev else "")
                      + (f" · 🎯{lv['nearest']['level']}" if lv else ""))
        except Exception as e:  # noqa: BLE001
            print(f"→ ⚠️ {e}")
        time.sleep(_pace(throttle))

    if shard is not None:
        write_shard_bundle(universe, shard[0], results, reversals, levels, table, total)
    else:
        results.sort(key=lambda r: r["score"], reverse=True)
        write_output(universe, results, total)
        write_reversals(universe, reversals, total)
        write_levels(universe, levels, total)
        if build_table:
            write_table(universe, table, total)
    return results


def _pace(throttle):
    """throttle + jitter ±0.1s + congestion penalty (ตอน Yahoo 429 ต่อเนื่อง)
    jitter กันยิงเป็นจังหวะเป๊ะ (ดู bot ชัด) · penalty ถ่วงเองเมื่อโดน rate-limit"""
    return max(0.0, throttle + random.uniform(-0.1, 0.1)) + congestion_penalty()


def build_table_row(symbol, daily, weekly, monthly, wa, row, rev_lv, rev):
    """แถว quant compact (array) สำหรับ master table us-all — ทุกตัวที่ candle พอ + floor กันเศษ
    floor: dv20 ≥ $1M และ close ≥ $1 (กัน penny/ไม่มีสภาพคล่องจริง) · คืน None ถ้าตก floor
    คอลัมน์ (ดู COLUMNS): [sym, close, dv20m, d_stage, w_stage, m_stage, w_conf, score, setup, near, rev]"""
    if len(daily) < 20:
        return None
    close = daily[-1]["close"]
    recent = daily[-20:]
    dv20m = round(mean(c["close"] * c["volume"] for c in recent) / 1e6, 1)   # ล้าน USD
    if close < 1.0 or dv20m < 1.0:
        return None
    da = analyze_stage(daily, MA_PERIOD["1d"], "1d") if len(daily) >= 160 else None
    ma = analyze_stage(monthly, MA_PERIOD["1mo"], "1mo") if len(monthly) >= 12 else None
    d_stage = da["stage"] if da else None
    w_stage = wa["stage"] if wa else None
    m_stage = ma["stage"] if ma else None
    w_conf = wa["confidence"] if wa else None
    score = row["score"] if row else None
    setup = ("B" if row["setup"] == "breakout" else "b") if row else None      # B=🚀 breakout · b=🌱 building
    near = rev_lv["nearest"]["level"] if rev_lv else None                       # s1/s2/r1/r2/avwap5y
    rev_flag = None
    if rev:
        top = next((r for r in rev if r["group"] == "top"), None)
        bottom = next((r for r in rev if r["group"] == "bottom"), None)
        rev_flag = "T" if top and not bottom else ("B" if bottom and not top else "TB")
    return [symbol, round(close, 2), dv20m, d_stage, w_stage, m_stage, w_conf,
            score, setup, near, rev_flag]


TABLE_COLUMNS = ["sym", "close", "dv20m", "d_stage", "w_stage", "m_stage",
                 "w_conf", "score", "setup", "near", "rev"]


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


def write_levels(universe, levels, scanned):
    """เขียน docs/<universe>-levels.json (Proximity Scanner — หุ้นใกล้แนวรับ/ต้าน/AVWAP-5y)
    เรียงตาม "ชิดแนวที่สุด" (|nearest.dist_pct| น้อยก่อน) — frontend แยกหมวด+gate เอง"""
    os.makedirs(DOCS_DIR, exist_ok=True)
    levels.sort(key=lambda r: abs(r["nearest"]["dist_pct"]))
    n_sup = sum(1 for r in levels if r["nearest"]["level"] in ("s1", "s2"))
    n_res = sum(1 for r in levels if r["nearest"]["level"] in ("r1", "r2"))
    n_avwap = sum(1 for r in levels if r["nearest"]["level"] == "avwap5y")
    payload = {
        "schema_version": 1,
        "universe": universe,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {"scanned": scanned, "found": len(levels),
                  "near_support": n_sup, "near_resistance": n_res, "near_avwap": n_avwap},
        "results": levels,
    }
    path = os.path.join(DOCS_DIR, f"{universe}-levels.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[scan] wrote {path} — {len(levels)} near-level "
          f"(sup={n_sup} res={n_res} avwap={n_avwap})")


def write_table(universe, table, scanned):
    """เขียน docs/<universe>-table.json (master quant table — ทุกตัว ไม่ใช่แค่ผ่าน gate)
    เรียง score มากก่อน (None ท้าย) แล้ว dv20 มากก่อน — frontend sort/filter เองได้"""
    os.makedirs(DOCS_DIR, exist_ok=True)
    table.sort(key=lambda r: (r[7] if r[7] is not None else -1, r[2]), reverse=True)
    payload = {
        "schema_version": 1,
        "universe": universe,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "columns": TABLE_COLUMNS,
        "stats": {"scanned": scanned, "rows": len(table)},
        "results": table,
    }
    path = os.path.join(DOCS_DIR, f"{universe}-table.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[scan] wrote {path} — {len(table)} rows")


def write_shard_bundle(universe, k, results, reversals, levels, table, scanned):
    """เขียน docs/<universe>-shard{k}.json = มัด 4 list ของ shard เดียว (artifact — ไม่ commit)
    merge_shards.py รวมทุก shard → 4 ไฟล์ final ตอน publish"""
    os.makedirs(DOCS_DIR, exist_ok=True)
    payload = {
        "universe": universe,
        "shard": k,
        "scanned": scanned,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "reversals": reversals,
        "levels": levels,
        "table": table,
    }
    path = os.path.join(DOCS_DIR, f"{universe}-shard{k}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[scan] wrote {path} — shard {k}: {len(results)} setups / "
          f"{len(reversals)} rev / {len(levels)} levels / {len(table)} table rows")


def _parse_shard(s):
    """'--shard 3/8' → (3, 8) พร้อม validate · คืน None ถ้าไม่ใส่"""
    if not s:
        return None
    try:
        k, n = s.split("/")
        k, n = int(k), int(n)
        if not (0 <= k < n) or n < 1:
            raise ValueError
        return (k, n)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(f"--shard ต้องเป็นรูป K/N (0≤K<N) ได้ '{s}'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True,
                    choices=["nasdaq100", "sp500", "sp400", "sp600", "us-all"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--throttle", type=float, default=0.25)
    ap.add_argument("--shard", type=_parse_shard, default=None,
                    help="K/N เช่น 3/8 = ทำเฉพาะหุ้น index k::n (ใช้กับ us-all universe ใหญ่)")
    args = ap.parse_args()
    scan(args.universe, limit=args.limit, throttle=args.throttle, shard=args.shard)


if __name__ == "__main__":
    sys.exit(main())
