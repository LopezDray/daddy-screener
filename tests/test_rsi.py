#!/usr/bin/env python3
"""
RSI ในตาราง Universe ต้องเป็นเลขเดียวกับหน้าเจาะลึก (app.js `rsi()` ของ DaddyInvestor)

ทำไมต้องมี: ตาราง us-all-table.json คอลัมน์ `rsi` (2026-10-04) ถูกเอาไปโชว์คู่กับหน้าเจาะลึก
ถ้าสูตรเพี้ยน (SMA แทน Wilder / seed ต่างกัน) ผู้ใช้จะเห็น RSI 2 ค่าของหุ้นตัวเดียวกัน
และชิป "RSI ต่ำกว่า 30" จะคัดหุ้นที่หน้าเจาะลึกบอกว่า 34 — คลาสบั๊ก "เลขไม่ตรงกันเงียบ ๆ"

🔒 เลขคาดหวังข้างล่าง **คำนวณจาก app.js rsi() ตัวจริง** (node · ซีรีส์ integer-LCG เดียวกันเป๊ะ)
   และฝั่ง DaddyInvestor มี tests/screener_rsi_parity.mjs ที่รันเลขชุดเดียวกันกับ app.js ⇒
   แก้สูตรฝั่งไหนฝั่งเดียว = แดงฝั่งนั้นทันที
   ซีรีส์ใช้จำนวนเต็มล้วน (Park-Miller · หน่วยสตางค์) — ไม่มี sin/cos/round ที่ Python กับ JS ปัดต่างกัน

รัน: python tests/test_rsi.py   ($0 · ไม่แตะ network)
"""
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from screener.indicators import rsi_wilder  # noqa: E402
import run_scan as rs  # noqa: E402

_pass, _fail = 0, 0


def check(cond, label):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  ✓ {label}")
    else:
        _fail += 1
        print(f"  ✗ {label}")


def series(n, seed0):
    """เหมือน rsi_expect / screener_rsi_parity.mjs ทุกตัวอักษร — อย่าแก้ข้างเดียว"""
    seed, cents, out = seed0, 10000, []
    for _ in range(n):
        seed = (seed * 16807) % 2147483647
        step = (seed % 301) - 150
        cents = max(100, cents + step)
        out.append(cents / 100)
    return out


# เลขจาก app.js rsi() ตัวจริง (2026-10-04)
EXPECT = {
    "a_last": 48.38368218966813,   # series(400, 12345) ทั้งเส้น
    "a_200": 66.84739135140114,    # 201 แท่งแรก
    "a_15": 63.583815028901796,    # 15 แท่ง = แท่งแรกที่มีค่า (seed ล้วน)
    "b_last": 41.51444238426843,   # series(60, 777)
}


def near(x, y, tol=1e-9):
    return x is not None and abs(x - y) <= tol


def main():
    a, b = series(400, 12345), series(60, 777)
    print("RSI Wilder parity กับ app.js rsi():")
    check(a[:3] == [99.55, 98.97, 99.83] and a[-3:] == [100.81, 100.58, 100.1],
          "ซีรีส์ทดสอบตรงกับฝั่ง JS (หัว/ท้าย)")
    check(near(rsi_wilder(a), EXPECT["a_last"]), f"400 แท่ง = {EXPECT['a_last']:.6f}")
    check(near(rsi_wilder(a[:201]), EXPECT["a_200"]), f"201 แท่ง = {EXPECT['a_200']:.6f}")
    check(near(rsi_wilder(a[:15]), EXPECT["a_15"]), f"15 แท่ง (seed ล้วน) = {EXPECT['a_15']:.6f}")
    check(near(rsi_wilder(b), EXPECT["b_last"]), f"ซีรีส์ที่ 2 = {EXPECT['b_last']:.6f}")

    print("ขอบ:")
    check(rsi_wilder(a[:14]) is None, "14 แท่ง (ไม่เกิน period) ⇒ None ไม่เดา")
    check(rsi_wilder([]) is None and rsi_wilder(None) is None, "ว่าง/None ⇒ None ไม่ throw")
    check(rsi_wilder([float(i) for i in range(1, 40)]) == 100.0, "ขึ้นล้วน (avgLoss=0) ⇒ 100 แบบ app.js")
    check(near(rsi_wilder([50.0 - i * 0.5 for i in range(40)]), 0.0, 1e-12), "ลงล้วน ⇒ 0")

    print("สัญญากับ table:")
    cols = rs.TABLE_COLUMNS
    check(cols[16:19] == ["s1", "r1", "rsi"], "s1/r1/rsi ต่อท้ายที่ index 16-18 (ไม่แทรกกลาง)")
    d0 = date(2024, 1, 1)
    daily = [{"time": (d0 + timedelta(days=i)).isoformat(), "open": c, "high": c * 1.01,
              "low": c * 0.99, "close": c, "volume": 2_000_000}
             for i, c in enumerate(series(400, 12345))]
    lv = {"s1": 99.1234, "r1": 101.5, "dist": {"s2": 3.1, "r2": -2.2, "avwap5y": 4.4},
          "nearest": {"level": "r1", "dist_pct": -1.38}}
    row = rs.build_table_row("TEST", daily, rs.resample(daily, "1wk"), rs.resample(daily, "1mo"),
                             None, None, lv, [])
    check(row is not None and len(row) == len(cols), f"แถวยาว {len(cols)} คอลัมน์")
    if row:
        check(row[16] == 99.1234 and row[17] == 101.5, "s1/r1 คัดลอกจาก levels row ตรง ๆ (ไม่ปัด/ไม่คำนวณใหม่)")
        check(row[18] == round(EXPECT["a_last"], 1), f"rsi ในแถว = {round(EXPECT['a_last'], 1)} (ปัด 1 ตำแหน่ง)")
    row2 = rs.build_table_row("NOLV", daily, rs.resample(daily, "1wk"), rs.resample(daily, "1mo"),
                              None, None, None, [])
    check(row2 is not None and row2[16] is None and row2[17] is None and row2[18] is not None,
          "ไม่มี levels row ⇒ s1/r1 = None แต่ rsi ยังมีค่า")

    print(f"\n{'✅' if not _fail else '❌'} test_rsi: {_pass} ผ่าน / {_fail} ตก")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
