#!/usr/bin/env python3
"""
นำร่อง 🌊 — สุ่มหุ้นข้ามทั้ง us-all แล้วนับว่าติดป้าย "กำลังเดินคลื่น" กี่ตัว

ทำไมต้องมี: ก่อนออกแบบ UI ต้องรู้ตัวเลขจริงว่าทั้งตลาดติดป้ายกี่ตัว
("~100 ตัว" ที่เคยพูดกันมาจาก 674 ตัว NAS100+SP500 ไม่ใช่ทั้ง universe — ห้ามอ้างเป็นข้อเท็จจริง)
ถ้าติดเยอะมาก = ต้องแยกชั้น (ขั้น 3 / ขั้น 4) · ถ้าน้อย = ชิปเดียวพอ

รัน:  python scripts/pilot_elliott.py --n 300
$0 — Yahoo ฟรีล้วน ไม่แตะ FMP/Supabase · seed คงที่ = สุ่มชุดเดิมทุกครั้ง (รันซ้ำเทียบกันได้)
"""

import argparse
import json
import os
import random
import sys
import time
from statistics import mean

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from screener.elliott import current_partial          # noqa: E402
from screener.fetch_yahoo import fetch_daily, MIN_CANDLES  # noqa: E402

UNIVERSE = os.path.join(ROOT, "screener", "universes", "us-all.json")
LIVE_TABLE = os.path.join(ROOT, "docs", "us-all-table.json")


def _live_table_rows():
    """จำนวนแถวใน us-all-table.json รอบล่าสุด = ฐานคูณที่ถูกต้อง (นับหลัง floor แล้ว)"""
    try:
        return len(json.load(open(LIVE_TABLE, encoding="utf-8"))["results"])
    except (OSError, KeyError, json.JSONDecodeError):
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300, help="จำนวนหุ้นที่สุ่ม")
    ap.add_argument("--seed", type=int, default=20260801)
    ap.add_argument("--throttle", type=float, default=0.3)
    ap.add_argument("--out", default="", help="เขียนผลดิบเป็น JSON (เว้นว่าง = ไม่เขียน)")
    args = ap.parse_args()

    uni = json.load(open(UNIVERSE, encoding="utf-8"))["symbols"]
    syms = [s["symbol"] for s in uni]
    random.Random(args.seed).shuffle(syms)
    syms = syms[:args.n]
    print(f"[pilot] us-all = {len(uni)} ตัว · สุ่ม {len(syms)} (seed {args.seed})", flush=True)

    tally, rows = {}, []
    skipped = floored = errs = 0
    t0 = time.time()
    for i, sym in enumerate(syms, 1):
        try:
            daily = fetch_daily(sym, rng="5y")
            if len(daily) < MIN_CANDLES["1d"]:
                skipped += 1
            else:
                close = daily[-1]["close"]
                dv20m = mean(c["close"] * c["volume"] for c in daily[-20:]) / 1e6
                if close < 1.0 or dv20m < 1.0:        # floor เดียวกับ build_table_row
                    floored += 1
                else:
                    r = current_partial(daily, "1d")
                    code = r["code"] if r else None
                    tally[code] = tally.get(code, 0) + 1
                    if r:
                        rows.append([sym, code, r["age_bars"], round(dv20m, 1)])
        except Exception as e:  # noqa: BLE001
            errs += 1
            print(f"  ⚠️ {sym}: {e}", flush=True)
        if i % 25 == 0:
            hit = sum(v for k, v in tally.items() if k)
            print(f"  {i}/{len(syms)} · ติดป้าย {hit} · {time.time()-t0:.0f}s", flush=True)
        time.sleep(args.throttle)

    in_table = sum(tally.values())
    hit = sum(v for k, v in tally.items() if k)
    print("\n" + "=" * 64)
    print(f"อยู่ใน table จริง (ผ่าน floor): {in_table}   "
          f"[candle ไม่พอ {skipped} · ตก floor {floored} · error {errs}]")
    if not in_table:
        print("ไม่มีตัวอย่างที่ใช้ได้ — ดึง Yahoo ไม่สำเร็จ?")
        return 1
    print(f"ติดป้าย 🌊 กำลังเดินคลื่น    : {hit} = {hit/in_table*100:.1f}% ของ table")
    for k in ("4u", "4d", "3u", "3d"):
        v = tally.get(k, 0)
        print(f"   {k}: {v:4d}  ({v/in_table*100:.1f}%)")
    # คาดการณ์ต้องคูณด้วย "จำนวนแถวที่อยู่ใน table จริง" ไม่ใช่ขนาด universe ก่อน floor
    # (universe ~5.5k → หลัง floor เหลือ ~3.8k · ใช้เลขก่อน floor จะเฟ้อ ~45%)
    table_rows = _live_table_rows()
    if table_rows:
        print(f"\nคาดการณ์ทั้งตลาด ≈ {round(hit/in_table*table_rows)} ตัวติดป้าย "
              f"(จาก {table_rows} แถวใน us-all-table.json รอบล่าสุด)")
    else:
        print(f"\nอัตราติดป้าย {hit/in_table*100:.1f}% — ยังไม่มี docs/us-all-table.json ให้คูณ")
    rows.sort(key=lambda r: -r[3])
    print("\n25 ตัวที่ dollar-volume สูงสุด [sym, code, อายุ(แท่ง), dv20m]:")
    for r in rows[:25]:
        print("  ", r)

    if args.out:
        json.dump({"tally": tally, "rows": rows, "in_table": in_table,
                   "universe": len(uni), "n": len(syms), "seed": args.seed},
                  open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"\n[pilot] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
