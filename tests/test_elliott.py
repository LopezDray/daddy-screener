#!/usr/bin/env python3
"""
tests/test_elliott.py — 🌊 partial Elliott count ที่ป้อนคอลัมน์ `ew` ของ us-all-table.json

รัน: python tests/test_elliott.py      # $0 ไม่แตะ network

ครอบ 2 ชั้น:
  1. self-test ของ screener/elliott.py (รูปทรง R1/R2/R4 · ด่านตาย · ด่านอายุ · สมมาตร)
  2. สัญญากับ table — build_table_row ต้องคาย `ew` เป็นคอลัมน์สุดท้าย และค่าที่ยอมรับได้
     มีแค่ None/"3u"/"4u"/"3d"/"4d" (frontend อ่านตาม index → ห้ามเลื่อน ห้ามโผล่ค่าประหลาด)
"""

import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_scan as rs                                    # noqa: E402
from screener import elliott as ew                       # noqa: E402

VALID = {None, "3u", "4u", "3d", "4d"}
_fails = []


def check(cond, name):
    print(("  ✅ " if cond else "  ❌ ") + name)
    if not cond:
        _fails.append(name)


def test_engine_self_test():
    print("engine self-test:")
    check(ew.self_test() == 0, "screener.elliott self-test ผ่านทั้งหมด")


def test_table_contract():
    print("\nสัญญากับ us-all-table.json:")
    check(rs.TABLE_COLUMNS[-1] == "ew", "`ew` เป็นคอลัมน์สุดท้าย (คอลัมน์ใหม่ต่อท้ายเสมอ)")
    check(rs.TABLE_COLUMNS.count("ew") == 1, "ไม่มี `ew` ซ้ำ")
    # คอลัมน์เดิมต้องไม่ขยับ — frontend เก่าอ่านตาม index
    check(rs.TABLE_COLUMNS[:11] == ["sym", "close", "dv20m", "d_stage", "w_stage", "m_stage",
                                    "w_conf", "score", "setup", "near", "rev"],
          "11 คอลัมน์เดิมยังอยู่ตำแหน่งเดิมเป๊ะ")

    daily = _mk_daily()
    row = rs.build_table_row("AAPL", daily, rs.resample(daily, "1wk"),
                             rs.resample(daily, "1mo"), {"stage": 2, "confidence": 70},
                             None, None, [])
    check(row is not None and len(row) == len(rs.TABLE_COLUMNS),
          f"แถวยาว {len(rs.TABLE_COLUMNS)} คอลัมน์")
    check(row[-1] in VALID, f"ค่า ew อยู่ในชุดที่ยอมรับ (ได้ {row[-1]!r})")


def test_row_carries_real_count():
    """ซีรีส์ที่นับได้ 1-2-3-4 จริง → ค่าต้องไหลถึงแถว table ไม่ใช่ None เฉยๆ"""
    print("\nค่าจริงไหลถึงแถว table:")
    seq = ew._bull_1234()
    # เติม time + volume ให้ผ่าน floor (close ≥ $1 · dv20 ≥ $1M) และ resample ได้
    daily = [{**c, "time": _day(i), "volume": 2_000_000} for i, c in enumerate(seq)]
    code = ew.wave_code(daily, "1d")
    check(code == "4u", f"engine อ่านซีรีส์นี้ได้ 4u (ได้ {code!r})")
    row = rs.build_table_row("TEST", daily, rs.resample(daily, "1wk"),
                             rs.resample(daily, "1mo"), None, None, None, [])
    check(row is not None and row[-1] == "4u", "build_table_row คาย ew='4u' ในคอลัมน์สุดท้าย")


def test_complete_five_waves_stays_silent():
    """🔴 regression QCRH (08-01): หุ้นที่ **นับครบ 5 คลื่นแล้ว** ต้องไม่ติดป้ายในตาราง

    เดิมป้ายบอก "ถึงคลื่น 4" ขณะที่แผง Elliott ของหุ้นเดียวกันบอก "นับครบ 5 คลื่น"
    เพราะ engine ฝั่ง scan ไม่รู้จัก impulse ครบ 5 เลย → ต้องกันที่ระดับแถวด้วย
    ไม่ใช่แค่ระดับ engine (ค่านี้คือสิ่งที่ frontend อ่านจริง)
    """
    print("\nนับครบ 5 คลื่นแล้วต้องเงียบ (regression QCRH):")
    seq = ew._bull_12345()
    daily = [{**c, "time": _day(i), "volume": 2_000_000} for i, c in enumerate(seq)]
    st = ew.detect_state(daily, "1d")
    check(st is not None and st["state"] == "complete",
          f"engine อ่านซีรีส์นี้เป็น complete (ได้ {st and st['state']!r})")
    check(ew.wave_code(daily, "1d") is None, "wave_code เงียบ (None)")
    row = rs.build_table_row("DONE5", daily, rs.resample(daily, "1wk"),
                             rs.resample(daily, "1mo"), None, None, None, [])
    check(row is not None and row[-1] is None, "แถว table คาย ew=None ไม่ใช่ '4u'")


def test_bad_input_never_kills_row():
    """หุ้นตัวเดียวคำนวณคลื่นพัง ห้ามล้มทั้งแถว (คอลัมน์อื่นยังมีค่า)"""
    print("\nกันพังทั้งแถว:")
    daily = _mk_daily()
    orig = rs.wave_code
    rs.wave_code = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        row = rs.build_table_row("BOOM", daily, rs.resample(daily, "1wk"),
                                 rs.resample(daily, "1mo"), None, None, None, [])
    finally:
        rs.wave_code = orig
    check(row is not None and row[0] == "BOOM", "engine โยน exception → ยังได้แถว")
    check(row is not None and row[-1] is None, "ew = None (ไม่ใช่ค่าขยะ)")


def _day(i):
    return (date(2022, 1, 3) + timedelta(days=i)).isoformat()


def _mk_daily(n=400, close=50.0, vol=500_000):
    """candle ปลอมพอผ่าน len>=160 + dv20 = 50×500k = $25M ≥ floor (mirror test_shard_merge)"""
    return [{"time": _day(i), "open": close, "high": close + 1,
             "low": close - 1, "close": close, "volume": vol} for i in range(n)]


if __name__ == "__main__":
    test_engine_self_test()
    test_table_contract()
    test_row_carries_real_count()
    test_complete_five_waves_stays_silent()
    test_bad_input_never_kills_row()
    print("\n" + ("ALL PASS ✅" if not _fails else f"FAIL ❌ ({len(_fails)}): " + " · ".join(_fails)))
    sys.exit(1 if _fails else 0)
