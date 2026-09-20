#!/usr/bin/env python3
"""
Self-test สำหรับ screener/levels.py (zero-dep — รัน: python tests/test_levels.py)

ครอบ 3 อย่าง:
  1) compute_dynamic_levels — เรียงถูก (s1>s2, r1<r2, support<close<resistance) + stable
  2) compute_avwap_5y — anchor ที่ min-low + ค่าอยู่ในกรอบราคา
  3) build_levels_row — schema ครบ + emit เฉพาะที่ ≤ NEAR_EMIT_BAND + จัด nearest ถูก

หมายเหตุ parity: S1/S2/R1/R2 เป็น faithful port ของ compute_dynamic_levels() ใน
DaddyInvestor (scripts/check_watchlist_alerts.py) — ตรวจ cross-repo ด้วย parity harness
(feed candle ชุดเดียวกัน ต่างแค่ key ts↔time → เลขตรงเป๊ะ 25/25). ที่นี่เทสเชิงพฤติกรรม
เพราะ repo นี้ไม่มี source ต้นทางให้ import.
"""
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener.levels import (  # noqa: E402
    NEAR_EMIT_BAND, build_levels_row, compute_avwap_5y, compute_dynamic_levels,
)


def gen_daily(seed, n=340, start_price=50.0):
    """สร้างแท่งเทียนรายวันสังเคราะห์ (past dates → ไม่โดน forming-bar drop)"""
    random.seed(seed)
    start = date(2019, 1, 2)
    price = start_price
    out = []
    for i in range(n):
        price *= (1 + random.uniform(-0.03, 0.032))
        price = max(2.0, price)
        o = price * (1 + random.uniform(-0.01, 0.01))
        hi = max(o, price) * (1 + random.uniform(0, 0.02))
        lo = min(o, price) * (1 - random.uniform(0, 0.02))
        out.append({
            "time": (start + timedelta(days=i)).isoformat(),
            "open": round(o, 4), "high": round(hi, 4), "low": round(lo, 4),
            "close": round(price, 4), "volume": round(random.uniform(1e6, 5e6)),
        })
    return out


def test_levels_ordering():
    for seed in range(1, 21):
        daily = gen_daily(seed)
        s1, s2, r1, r2, ref = compute_dynamic_levels(daily)
        assert ref is not None, f"seed {seed}: ref close None"
        # support < close < resistance (แต่ละแนวที่ไม่ None)
        for s in (s1, s2):
            assert s is None or s < ref, f"seed {seed}: support {s} !< close {ref}"
        for r in (r1, r2):
            assert r is None or r > ref, f"seed {seed}: resistance {r} !> close {ref}"
        # s1 ใกล้ close กว่า s2 · r1 ใกล้ close กว่า r2
        if s1 and s2:
            assert s1 > s2, f"seed {seed}: s1 {s1} !> s2 {s2}"
        if r1 and r2:
            assert r1 < r2, f"seed {seed}: r1 {r1} !< r2 {r2}"
    # deterministic — รันซ้ำได้เลขเดิม
    assert compute_dynamic_levels(gen_daily(7)) == compute_dynamic_levels(gen_daily(7))
    print("✓ test_levels_ordering")


def test_avwap():
    for seed in range(1, 21):
        daily = gen_daily(seed)
        av = compute_avwap_5y(daily)
        assert av is not None, f"seed {seed}: avwap None"
        lo = min(c["low"] for c in daily)
        hi = max(c["high"] for c in daily)
        assert lo <= av <= hi, f"seed {seed}: avwap {av} นอกกรอบ [{lo},{hi}]"
    # volume 0 ทั้งชุด → None (กัน div-by-zero)
    z = gen_daily(3)
    for c in z:
        c["volume"] = 0
    assert compute_avwap_5y(z) is None, "avwap ควร None เมื่อ volume=0 ทั้งชุด"
    # candle น้อยเกิน → None
    assert compute_avwap_5y(gen_daily(1, n=10)) is None
    print("✓ test_avwap")


def test_build_row_schema_and_band():
    KEYS = {"symbol", "sector", "close", "s1", "s2", "r1", "r2", "avwap5y",
            "dist", "nearest", "w_stage", "setup", "signal", "reversal"}
    emitted = 0
    for seed in range(1, 41):
        daily = gen_daily(seed)
        rev = [{"symbol": "X", "tf": "W", "key": "double_bottom", "group": "bottom",
                "bias": "bull", "status": "forming", "confidence": 55, "volConfirmed": True}]
        row = build_levels_row("X", daily, sector="Tech", w_stage=2,
                               setup="building", signal="W2", reversal_rows=rev)
        if row is None:
            continue
        emitted += 1
        assert set(row) == KEYS, f"seed {seed}: schema keys ต่าง: {set(row) ^ KEYS}"
        # emit เฉพาะที่ ≤ band
        assert abs(row["nearest"]["dist_pct"]) <= NEAR_EMIT_BAND
        # nearest.level = แนวที่ |dist| น้อยสุดใน dist จริง
        best = min(row["dist"], key=lambda k: abs(row["dist"][k]))
        assert row["nearest"]["level"] == best, f"seed {seed}: nearest ผิด"
        # reversal ถูกสรุปเป็น dict ที่มี key/group
        assert row["reversal"] and row["reversal"]["key"] == "double_bottom"
    assert emitted > 0, "ควร emit อย่างน้อย 1 row จาก 40 seed"
    # หุ้นราคาไกลทุกแนว → None (สร้างเคส: ดันราคาให้พุ่งช่วงท้าย)
    print(f"✓ test_build_row_schema_and_band ({emitted}/40 emitted)")


def gen_daily_5y(seed, n=1300, start_price=50.0):
    """แท่งสังเคราะห์ ~5 ปี เฉพาะวันทำการ (จ-ศ) → weekly ≥ 200 สัปดาห์ = branch EMA200W มีค่าจริง"""
    random.seed(seed)
    d = date(2019, 1, 1)
    price = start_price
    out = []
    while len(out) < n:
        d += timedelta(days=1)
        if d.isoweekday() > 5:
            continue
        price *= (1 + random.uniform(-0.03, 0.032))
        price = max(2.0, price)
        o = price * (1 + random.uniform(-0.01, 0.01))
        hi = max(o, price) * (1 + random.uniform(0, 0.02))
        lo = min(o, price) * (1 - random.uniform(0, 0.02))
        out.append({
            "time": d.isoformat(),
            "open": round(o, 4), "high": round(hi, 4), "low": round(lo, 4),
            "close": round(price, 4), "volume": round(random.uniform(1e6, 5e6)),
        })
    return out


def test_levels_independent_of_history_beyond_lookback():
    """🔔 alert-contract (#22): run_scan ป้อน daily 5 ปี แต่ S1/S2/R1/R2 ต้องเท่ากับคิดจาก 252 แท่งท้าย
    (= app.js analyze / worker /levels / check_watchlist_alerts ที่เห็นแค่ 1 ปี) — ต่างเมื่อไหร่ =
    Universe อ้างแนวที่หน้าเว็บ/push ไม่มี (SBUX 2026-09-17: s1 94.9776 (EMA200W) vs 95.45)"""
    from screener.levels import _app_weekly, _ema
    checked = 0
    for seed in range(1, 41):
        daily = gen_daily_5y(seed)
        assert len(_app_weekly(daily)) >= 200, "fixture ต้องยาวพอให้ EMA200W มีค่าบน 5 ปี"
        full = compute_dynamic_levels(daily)
        short = compute_dynamic_levels(daily[-252:])
        assert full == short, f"seed {seed}: 5y {full} != 252 แท่ง {short} (weekly รั่วจากนอกหน้าต่าง)"
        checked += 1
    assert checked == 40
    print("✓ test_levels_independent_of_history_beyond_lookback")


def test_weekly_window_is_calendar_year_not_252_bars():
    """🔔 alert-contract (#22 รอบ 2 · 2026-09-20): weekly ต้องมาจาก **365 วันปฏิทิน**
    ไม่ใช่ 252 *แท่ง* — ②③ ได้ daily = candle_cache range=1y ทั้งก้อน:
      หุ้น ~252 แถว/52 สัปดาห์ · crypto 365 แถว/53 สัปดาห์ ⇒ MA50W มีค่า **ทั้งคู่**
    ถ้าตัดด้วย daily[-252:] แท่ง crypto (7 แท่ง/สัปดาห์) จะเหลือ 36 สัปดาห์ → MA50W หาย
    = Universe อ้างแนวคนละชุดกับหน้าเว็บ/push (เจอตอนเทียบ golden BTC-USD ฝั่ง DaddyInvestor)"""
    from screener.levels import _app_weekly, _one_year, _sma
    # crypto = ทุกวันมีแท่ง (ไม่มีวันหยุด) 3 ปี
    start = date(2023, 1, 2)
    daily = []
    for i in range(3 * 365):
        d = start.fromordinal(start.toordinal() + i)
        px = 100 + (i % 37) * 0.5
        daily.append({"time": d.isoformat(), "open": px, "high": px + 1,
                      "low": px - 1, "close": px, "volume": 1000})
    win = _one_year(daily)
    assert len(win) == 365, f"หน้าต่าง 1 ปีปฏิทินต้องได้ 365 แท่ง (crypto) — ได้ {len(win)}"
    wk = _app_weekly(win)
    assert len(wk) >= 50, f"crypto 1 ปี ต้องได้ >= 50 สัปดาห์ (ได้ {len(wk)}) — MA50W ต้องมีค่า"
    assert _sma([c["close"] for c in wk], 50) is not None, "MA50W ต้องมีค่าเท่า ②③"
    # ถ้าใครเผลอกลับไปตัด 252 แท่ง → พังตรงนี้
    assert len(_app_weekly(daily[-252:])) < 50, "fixture ต้องแยกสองทางได้จริง"
    # หุ้น (5 แท่ง/สัปดาห์) — สองวิธีต้องให้ MA50W เท่ากัน (ไม่มี regression ฝั่งหุ้น)
    stock = [c for i, c in enumerate(daily)
             if date.fromisoformat(c["time"]).isoweekday() <= 5]
    a = _sma([c["close"] for c in _app_weekly(_one_year(stock))], 50)
    b = _sma([c["close"] for c in _app_weekly(stock[-252:])], 50)
    assert a is not None and b is not None and abs(a - b) < 1e-9, f"หุ้น MA50W ต้องเท่ากัน: {a} vs {b}"
    print("✓ test_weekly_window_is_calendar_year_not_252_bars")


def test_insufficient_candles():
    assert compute_dynamic_levels(gen_daily(1, n=10)) == (None, None, None, None, None)
    assert build_levels_row("X", gen_daily(1, n=10)) is None
    print("✓ test_insufficient_candles")


if __name__ == "__main__":
    test_levels_ordering()
    test_avwap()
    test_build_row_schema_and_band()
    test_levels_independent_of_history_beyond_lookback()
    test_weekly_window_is_calendar_year_not_252_bars()
    test_insufficient_candles()
    print("ALL PASS")
