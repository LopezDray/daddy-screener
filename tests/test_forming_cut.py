#!/usr/bin/env python3
"""
test_forming_cut.py — S5 (2026-09-20) · กฎ "แท่งท้ายถือว่าปิดแล้วเมื่อไร" ต้องเท่ากับ DaddyInvestor 4 ports

เคสร่วม tests/fixtures/forming_cut_cases.json = **สำเนา** ของ DaddyInvestor/tests/fixtures/forming_cut_cases.json
(repo นี้ import ต้นทางไม่ได้ · เวลาต้นทางแก้ตารางต้องคัดลอกมาด้วย — ห้ามแก้ที่นี่ฝ่ายเดียว)
ตารางกฎ: US ปิด 16:10 ET (DST-aware) · .BK 09:40Z · crypto 00:00Z วันถัดไป · other = date < today UTC
ไม่ใช้เวลาจริง — ฉีด as_of ทุกเคส · รัน: python tests/test_forming_cut.py
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener.levels import bar_close_utc, compute_dynamic_levels, is_bar_closed, market_class_of  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "forming_cut_cases.json")
with open(FX, encoding="utf-8") as fh:
    CASES = json.load(fh)


def test_rule_table():
    for c in CASES["cases"]:
        got = is_bar_closed(c["symbol"], c["bar_date"], c["as_of"])
        assert got == c["expect"], f"{c['name']}: {c['symbol']} {c['bar_date']} @ {c['as_of']} → {got} (คาด {c['expect']})"
    print(f"✓ test_rule_table ({len(CASES['cases'])} เคส)")


def test_us_close_vs_zoneinfo():
    try:
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
    except Exception:
        print("- test_us_close_vs_zoneinfo skipped (no tzdata)")
        return
    d = date(2020, 1, 1)
    while d <= date(2030, 12, 31):
        want = datetime(d.year, d.month, d.day, 16, 10, tzinfo=ny).astimezone(timezone.utc)
        assert bar_close_utc("us", d.isoformat()) == want, d
        d += timedelta(days=1)
    print("✓ test_us_close_vs_zoneinfo")


def _gen(n=300, last="2026-06-18"):
    """แท่งสังเคราะห์วันทำการ จบที่ last (อดีต) — ค่าคงที่กันสุ่ม"""
    out, d, price = [], date.fromisoformat(last), 100.0
    while len(out) < n:
        if d.isoweekday() <= 5:
            price = 100.0 + 20.0 * ((len(out) * 7919) % 97) / 97.0
            out.append({"time": d.isoformat(), "open": price, "high": price + 1.5, "low": price - 1.5,
                        "close": price, "volume": 1e6})
        d -= timedelta(days=1)
    return list(reversed(out))


def test_levels_follow_rule():
    daily = _gen()
    bar = {"time": "2026-06-22", "open": 108.0, "high": 140.0, "low": 106.0, "close": 135.0, "volume": 1e6}
    base = compute_dynamic_levels(daily)                       # ไม่ส่ง symbol/as_of = กฎเดิม · แท่งท้ายอดีต ⇒ ไม่ตัด
    assert base[4] == daily[-1]["close"]
    cut = compute_dynamic_levels(daily + [bar], symbol="NVDA", as_of="2026-06-22T15:00:00Z")   # ระหว่างเทรด
    keep = compute_dynamic_levels(daily + [bar], symbol="NVDA", as_of="2026-06-22T20:10:00Z")  # 16:10 ET
    assert cut == base, "US ระหว่างเทรดต้องตัดแท่งท้าย"
    assert keep[4] == 135.0 and keep != base, "US 16:10 ET ต้องรวมแท่งท้าย"
    assert compute_dynamic_levels(daily + [bar], symbol="PTT.BK", as_of="2026-06-22T05:00:00Z") == base
    assert compute_dynamic_levels(daily + [bar], symbol="PTT.BK", as_of="2026-06-22T12:00:00Z")[4] == 135.0
    assert compute_dynamic_levels(daily + [bar], symbol="BTC-USD", as_of="2026-06-22T21:00:00Z") == base
    assert compute_dynamic_levels(daily + [bar], symbol="BTC-USD", as_of="2026-06-23T00:00:00Z")[4] == 135.0
    assert compute_dynamic_levels(daily + [bar], as_of="2026-06-22T23:00:00Z") == base            # กฎเดิม
    assert compute_dynamic_levels(daily + [bar], as_of="2026-06-23T00:00:00Z")[4] == 135.0
    assert market_class_of("^GSPC") == "us" and market_class_of("GC=F") == "other"
    print("✓ test_levels_follow_rule")


if __name__ == "__main__":
    test_rule_table()
    test_us_close_vs_zoneinfo()
    test_levels_follow_rule()
    print("ALL PASS")
