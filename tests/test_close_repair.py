#!/usr/bin/env python3
"""
close-repair port ที่ 3 (ALERT CONTRACT) — screener/fetch_yahoo.py

3 ports ต้องตัดสินเหมือนกัน: ② daddy-asset-worker.js · ③ check_watchlist_alerts.py (ต้นทาง) · ④ ที่นี่
เคสร่วมอยู่ฝั่ง DaddyInvestor (private) ⇒ ด่านเทียบเคสร่วมอยู่ที่นั่น
(tests/screener/test_close_repair_parity.py) · ไฟล์นี้คือด่านฝั่ง screener ที่รันได้ลำพัง

รัน: python tests/test_close_repair.py   ($0 ไม่แตะ network)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener.fetch_yahoo import _parse_result, yahoo_close_repair  # noqa: E402

_pass, _fail = 0, 0


def ok(cond, label, hint=""):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
        print(f"  ✗ {label}")
        if hint:
            print(f"      ↳ {hint}")


# 2026-08-03 12:00Z · แท่ง 08-03 = 1754179200
DAY = 86400
TS_0802, TS_0803 = 1785628800, 1785715200


def payload(close_last, vol_last=1_000_000, price=105.0, mkt_time=TS_0803 + 20 * 3600, **meta_over):
    meta = {"regularMarketPrice": price, "regularMarketTime": mkt_time, "gmtoffset": 0}
    meta.update(meta_over)
    return {
        "meta": meta,
        "timestamp": [TS_0802, TS_0803],
        "indicators": {"quote": [{
            "open":   [100.0, 102.0],
            "high":   [101.0, 110.0],
            "low":    [ 99.0, 100.0],
            "close":  [100.5, close_last],
            "volume": [900_000, vol_last],
        }]},
    }


def test_glitch_repaired():
    """อาการจริง 08-03: o/h/l/volume ครบ close=null → ต้องซ่อม ไม่ใช่ดรอป"""
    print("═══ ① แท่ง glitch ถูกซ่อม (ไม่ถอยไปใช้ session ก่อน)")
    rows = _parse_result(payload(None))
    ok(len(rows) == 2, f"ได้ 2 แท่ง (ได้ {len(rows)})", "ก่อนแพตช์จะได้ 1 = ทั้งกระดานล้า 1 วัน")
    if len(rows) == 2:
        ok(rows[-1]["time"] == "2026-08-03", f"แท่งท้ายเป็นวันนี้ (ได้ {rows[-1]['time']})")
        ok(abs(rows[-1]["close"] - 105.0) < 1e-9, f"close = regularMarketPrice (ได้ {rows[-1]['close']})")
        ok(rows[-1]["volume"] == 1_000_000.0, "volume ของจริงไม่ถูกแตะ")


def test_volume_null_not_faked():
    """🔴 regression ที่ตรวจสวนจับได้: close=null **และ** volume=null ⇒ ห้ามซ่อม

    ถ้าซ่อม บรรทัด `float(v) if v is not None else 0.0` จะยัด volume=0.0 เข้าท่อ
    → patterns.py:147 ตัดสิน volConfirmed=False → :229 หักคะแนน 10 แต้ม = ลดเกรดเบรกจริงเงียบ ๆ
    ก่อนแพตช์แท่งนี้ถูกดรอปทั้งแท่ง จึงไม่เคยมี volume=0 หลุดเข้ามา — ห้ามเปิดช่องใหม่
    """
    print("═══ ② close=null + volume=null → ดรอป ไม่ยัด volume=0")
    rows = _parse_result(payload(None, vol_last=None))
    ok(len(rows) == 1, f"ดรอปแท่งที่ volume หายด้วย (ได้ {len(rows)} แท่ง)",
       "ยอมล้า 1 วัน ดีกว่าโชว์ volConfirmed ที่โกหก")
    ok(all(r["volume"] > 0 for r in rows), "ไม่มีแถว volume=0 หลุดเข้าท่อ")


def test_guards_reject_bad_meta():
    """เงื่อนไข 4 ข้อ — ผิดข้อไหนก็ไม่ซ่อม (ยอมล้าดีกว่าเดาราคา)"""
    print("═══ ③ เงื่อนไขกันเดาราคา")
    cases = [
        ("meta ไม่มีราคา", dict(price=None)),
        ("ราคา 0", dict(price=0.0)),
        ("ราคาอยู่นอกช่วง low..high", dict(price=999.0)),
        ("regularMarketTime เป็นวันถัดไป (span > 0)", dict(mkt_time=TS_0803 + DAY + 3600)),
        ("regularMarketTime ก่อนแท่ง (span < 0)", dict(mkt_time=TS_0802 - 3600)),
    ]
    for name, over in cases:
        rows = _parse_result(payload(None, **over))
        ok(len(rows) == 1, f"{name} → ไม่ซ่อม (ได้ {len(rows)} แท่ง)")


def test_no_repair_when_close_present():
    """close มาปกติ → repair ต้องไม่แตะอะไรเลย (self-healing ตอน Yahoo ซ่อมเอง)"""
    print("═══ ④ close ปกติ → ไม่แตะ")
    rows = _parse_result(payload(107.25))
    ok(len(rows) == 2, "ได้ครบ 2 แท่ง")
    ok(rows[-1]["close"] == 107.25, f"ใช้ close ของจริง ไม่ทับด้วย meta (ได้ {rows[-1]['close']})")


def test_repair_factory_contract():
    """yahoo_close_repair คืน None เมื่อ meta ใช้ไม่ได้ — signature ตรง ③"""
    print("═══ ⑤ สัญญาของ factory")
    ok(yahoo_close_repair({}, 0) is None, "meta ว่าง → None")
    ok(yahoo_close_repair(None, 0) is None, "result เป็น None → None")
    ok(yahoo_close_repair({"meta": {"regularMarketPrice": "x", "regularMarketTime": 1}}, 0) is None,
       "ราคา parse ไม่ได้ → None")
    r = yahoo_close_repair(payload(None), 0)
    ok(callable(r), "meta ดี → คืน callable")
    if callable(r):
        ok(r("2026-08-03", 100.0, 110.0) == 105.0, "เรียกตรง ๆ ได้ราคา")
        ok(r("ไม่ใช่วันที่", 100.0, 110.0) is None, "bar_date พัง → None")
        ok(r("2026-08-03", None, 110.0) is None, "low หาย → None")
        ok(r("2026-08-03", 110.0, 100.0) is None, "high < low → None")


if __name__ == "__main__":
    test_glitch_repaired()
    test_volume_null_not_faked()
    test_guards_reject_bad_meta()
    test_no_repair_when_close_present()
    test_repair_factory_contract()
    print(f"\n{'ALL PASS ✅' if not _fail else '💥 FAIL'} — ผ่าน {_pass} / ตก {_fail}")
    sys.exit(1 if _fail else 0)
