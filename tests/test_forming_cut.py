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
from screener import fetch_yahoo  # noqa: E402
from screener.fetch_yahoo import drop_forming_bar, fetch_daily  # noqa: E402

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


def test_fetch_layer_rule_table():
    """#7C — drop_forming_bar (ชั้นดึง) ต้องตัดสินเท่า is_bar_closed ทุกเคสในตารางร่วม"""
    for c in CASES["cases"]:
        d = [{"time": "2020-01-02", "close": 1.0}, {"time": c["bar_date"], "close": 2.0}]
        got = len(drop_forming_bar(c["symbol"], d, c["as_of"]))
        assert got == (2 if c["expect"] else 1), f"{c['name']}: เหลือ {got} แท่ง"
    assert drop_forming_bar("NVDA", [], "2026-06-22T15:00:00Z") == []
    one = [{"time": "2026-06-22", "close": 1.0}]
    assert drop_forming_bar("NVDA", one, "2026-06-22T15:00:00Z") is one          # len 1 ไม่ตัด (เท่า levels.py)
    print(f"✓ test_fetch_layer_rule_table ({len(CASES['cases'])} เคส)")


class _FakeResp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _payload(n, last="2026-06-22"):
    days, d = [], date.fromisoformat(last)
    while len(days) < n:
        if d.isoweekday() <= 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    ts = [int(datetime(x.year, x.month, x.day, 13, 30, tzinfo=timezone.utc).timestamp()) for x in days]
    px = [100.0 + i for i in range(n)]
    return json.dumps({"chart": {"result": [{"meta": {}, "timestamp": ts, "indicators": {"quote": [{
        "open": px, "high": [p + 1 for p in px], "low": [p - 1 for p in px], "close": px,
        "volume": [1e6] * n}]}}]}}).encode()


def test_fetch_daily_cuts_forming_bar():
    """fetch_daily ตัดแท่งวันนี้ที่ยังวิ่ง · หุ้นกับดัชนีเทียบ RS (SPY) ตัดพร้อมกัน ⇒ RS ไม่เหลื่อมวัน"""
    orig = fetch_yahoo.urllib.request.urlopen
    fetch_yahoo.urllib.request.urlopen = lambda req, timeout=None: _FakeResp(_payload(31))
    try:
        live = fetch_daily("NVDA", as_of="2026-06-22T15:00:00Z")
        idx = fetch_daily("SPY", as_of="2026-06-22T15:00:00Z")
        after = fetch_daily("NVDA", as_of="2026-06-22T20:10:00Z")
    finally:
        fetch_yahoo.urllib.request.urlopen = orig
    assert len(live) == 30 and live[-1]["time"] == "2026-06-19", live[-1]
    assert len(idx) == 30 and idx[-1]["time"] == live[-1]["time"], "ดัชนี RS ต้องจบวันเดียวกับหุ้น"
    assert len(after) == 31 and after[-1]["time"] == "2026-06-22"
    assert market_class_of("SPY") == market_class_of("QQQ") == market_class_of("IJH") == market_class_of("IJR") == "us"
    print("✓ test_fetch_daily_cuts_forming_bar")


def test_table_close_equals_levels_ref():
    """แถว Universe: close ของตาราง (daily[-1]) ต้องเป็นแท่งเดียวกับ ref ของแนว — เดิมกดรันกลางวัน = คนละแท่ง"""
    daily = _gen()
    bar = {"time": "2026-06-22", "open": 108.0, "high": 140.0, "low": 106.0, "close": 135.0, "volume": 1e6}
    as_of = "2026-06-22T15:00:00Z"
    raw = daily + [bar]
    assert compute_dynamic_levels(raw, symbol="NVDA", as_of=as_of)[4] != raw[-1]["close"]   # อาการเดิม
    cut = drop_forming_bar("NVDA", raw, as_of)
    assert compute_dynamic_levels(cut, symbol="NVDA", as_of=as_of)[4] == round(cut[-1]["close"], 4)
    assert compute_dynamic_levels(cut, symbol="NVDA", as_of=as_of) == compute_dynamic_levels(raw, symbol="NVDA", as_of=as_of)
    print("✓ test_table_close_equals_levels_ref")


if __name__ == "__main__":
    test_rule_table()
    test_us_close_vs_zoneinfo()
    test_levels_follow_rule()
    test_fetch_layer_rule_table()
    test_fetch_daily_cuts_forming_bar()
    test_table_close_equals_levels_ref()
    print("ALL PASS")
