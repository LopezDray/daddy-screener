#!/usr/bin/env python3
"""
levels.py — Proximity scanner engine (แนวรับ/แนวต้าน S1-S2/R1-R2 + AVWAP จากจุดต่ำสุด 5 ปี)

จุดประสงค์: หาหุ้นที่ "ราคาปิดใกล้แนว" (support/resistance/AVWAP) เพื่อดันเข้า "แนวพิจารณา"

⚖️ S/R = faithful port ของ compute_dynamic_levels() ใน DaddyInvestor
   (scripts/check_watchlist_alerts.py) ซึ่งเองก็ port มาจาก app.js analyze() →
   เลข S1/S2/R1/R2 ที่นี่ = เลขเดียวกับที่หน้าเว็บ/alert โชว์ (กัน 3rd-impl drift)
   ต่างจากต้นทางแค่ candle key: ต้นทางใช้ "ts" (unix) → ที่นี่ใช้ "time" (YYYY-MM-DD string)
   ตรวจ parity ด้วย tests/test_levels.py (feed candle ชุดเดียวกัน → S/R ต้องตรงเป๊ะ)

AVWAP-5y = ของใหม่ (ไม่มีในระบบเดิม): anchor = แท่ง low ต่ำสุดของ 5 ปี →
   cumulative Σ(typical_price × volume) / Σ(volume) ตั้งแต่ anchor ถึงปัจจุบัน

stdlib ล้วน — ตาม ethos ของ repo (ไม่มี dependency)
"""

from datetime import date, datetime, timezone

# ── ระยะ emit: เก็บเฉพาะหุ้นที่ปิดห่างจากแนวใดแนวหนึ่ง ≤ นี้ (%) → "อยู่ในแนวพิจารณา" ──
NEAR_EMIT_BAND = 8.0
LOOKBACK = 252              # เท่ากับต้นทาง (analyze() ใช้ 252 วันทำการ)
LEVEL_CHANGE_MIN = 0.0      # ไม่ใช้ที่นี่ (มีใน alert เพื่อ latch) — คงชื่อไว้เฉยๆ


# ── S/R helpers — port ตรงจาก check_watchlist_alerts.py (mirror app.js) ──────────
def _sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    val = sum(values[:period]) / period  # seed with SMA
    for v in values[period:]:
        val = v * k + val * (1 - k)
    return val


def _app_weekly(daily):
    """group daily → weekly (ISO week, Monday) by date of "time" — mirror app.js toWeeklyCandles
    (ต้นทางใช้ c["ts"] → datetime.fromtimestamp; ที่นี่ใช้ c["time"] = 'YYYY-MM-DD')"""
    weeks, key, cur = [], "", None
    for c in daily:
        d = date.fromisoformat(c["time"])
        ws = d.fromordinal(d.toordinal() - (d.isoweekday() - 1))
        k = ws.isoformat()
        if k != key:
            if cur:
                weeks.append(cur)
            key, cur = k, dict(c)
            continue
        cur["high"] = max(cur["high"], c["high"])
        cur["low"] = min(cur["low"], c["low"])
        cur["close"] = c["close"]
    if cur:
        weeks.append(cur)
    return weeks


def _app_pivots(c):
    """nearestPivots — 3-bar window each side, keep last 36 (mirror app.js)"""
    piv = []
    for i in range(3, len(c) - 3):
        sl = c[i - 3:i + 4]
        if c[i]["low"] == min(x["low"] for x in sl):
            piv.append(("support", c[i]["low"]))
        if c[i]["high"] == max(x["high"] for x in sl):
            piv.append(("resistance", c[i]["high"]))
    return piv[-36:]


def _app_unique(vals):
    """uniqueLevels — sort asc, drop levels within 1.2% of an earlier one (mirror app.js)"""
    out = []
    for v in sorted(x for x in vals if x and x > 0):
        if not any(abs(x - v) / v < 0.012 for x in out):
            out.append(v)
    return out


def _pick_two(cands, last, kind):
    """pickTwoLevels — support strictly < last-buf, resistance > last+buf; nearest two (mirror app.js)"""
    buf = last * 0.003
    side = [v for v in cands if (v < last - buf if kind == "support" else v > last + buf)]
    side.sort(reverse=(kind == "support"))
    return side[:2]


def compute_dynamic_levels(daily_candles, lookback=LOOKBACK):
    """
    Faithful port ของ compute_dynamic_levels() ใน DaddyInvestor → S1/S2/R1/R2 == เลขหน้าเว็บ
    daily_candles = list ของ {open,high,low,close,volume,time="YYYY-MM-DD"}
    คืน (s1, s2, r1, r2, ref_close) — level อาจเป็น None · ref_close = แท่งปิดล่าสุด (None ถ้าไม่พอ)
    """
    daily = [c for c in (daily_candles or []) if c and c.get("close") is not None and c.get("time")]
    if len(daily) < 30:
        return None, None, None, None, None
    # กันแท่ง "วันนี้" ที่ยังไม่ปิด (forming) — แอปก็ใช้เฉพาะแท่งที่ปิดแล้ว
    today = datetime.now(timezone.utc).date()
    if len(daily) > 1 and date.fromisoformat(daily[-1]["time"]) >= today:
        daily = daily[:-1]
    if len(daily) < 30:
        return None, None, None, None, None

    scoped = daily[-lookback:]
    weekly = _app_weekly(daily)
    wcloses = [c["close"] for c in weekly]
    wma50 = _sma(wcloses, 50)
    wema200 = _ema(wcloses, 200)

    last = scoped[-1]["close"]
    hi = max(c["high"] for c in scoped)
    lo = min(c["low"] for c in scoped)
    rng = hi - lo
    fib = {
        "236": hi - rng * 0.236, "382": hi - rng * 0.382, "500": hi - rng * 0.5,
        "618": hi - rng * 0.618, "786": hi - rng * 0.786,
        "1272": hi + rng * 0.272, "1618": hi + rng * 0.618,
    }

    def _mlow(n):
        return min(c["low"] for c in scoped[-n:])

    def _mhigh(n):
        return max(c["high"] for c in scoped[-n:])

    piv = _app_pivots(scoped)

    sup_c = _app_unique(
        [fib["236"], fib["382"], fib["500"], fib["618"], fib["786"]]
        + ([wma50] if wma50 else []) + ([wema200] if wema200 else [])
        + [_mlow(20), _mlow(60), _mlow(120), lo]
        + [v for t, v in piv if t == "support"]
    )
    res_c = _app_unique(
        [fib["236"], fib["382"], fib["500"], fib["618"], hi,
         _mhigh(20), _mhigh(60), _mhigh(120), fib["1272"], fib["1618"]]
        + [v for t, v in piv if t == "resistance"]
    )

    sup = _pick_two(sup_c, last, "support")
    res = _pick_two(res_c, last, "resistance")
    while len(sup) < 2:
        sup.append(last * (1 - (len(sup) + 1) * 0.07))
    while len(res) < 2:
        res.append(last * (1 + (len(res) + 1) * 0.06))
    sup.sort(reverse=True)
    res.sort()

    s1 = round(sup[0], 4) if len(sup) > 0 else None
    s2 = round(sup[1], 4) if len(sup) > 1 else None
    r1 = round(res[0], 4) if len(res) > 0 else None
    r2 = round(res[1], 4) if len(res) > 1 else None
    return s1, s2, r1, r2, round(last, 4)


def compute_avwap_5y(daily_candles):
    """AVWAP anchored ที่จุดต่ำสุด (min low) ของช่วง 5 ปี → คืนค่าเส้น ณ ปัจจุบัน (None ถ้าไม่พอ)
    typical price = (high+low+close)/3 · cumulative จาก anchor ถึงแท่งสุดท้าย"""
    scoped = [c for c in (daily_candles or [])
              if c and c.get("low") is not None and c.get("close") is not None]
    if len(scoped) < 30:
        return None
    anchor = min(range(len(scoped)), key=lambda i: scoped[i]["low"])
    num = 0.0
    den = 0.0
    for c in scoped[anchor:]:
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        v = c.get("volume") or 0.0
        num += tp * v
        den += v
    if den <= 0:
        return None
    return round(num / den, 4)


def _pick_reversal(reversal_rows):
    """เลือก reversal ที่ "ชัดสุด" ของ symbol (confirmed ก่อน forming · confidence สูงก่อน)"""
    if not reversal_rows:
        return None
    rank = {"confirmed": 0, "forming": 1}
    best = sorted(reversal_rows,
                  key=lambda r: (rank.get(r.get("status"), 2), -r.get("confidence", 0)))[0]
    return {"key": best.get("key"), "tf": best.get("tf"),
            "group": best.get("group"), "status": best.get("status"),
            "bias": best.get("bias")}


def build_levels_row(symbol, daily, sector=None, w_stage=None, setup=None,
                     signal=None, reversal_rows=None):
    """
    คืน proximity row 1 ตัว (dict) หรือ None ถ้า:
      - candle ไม่พอ / ราคาอ้างอิงไม่ได้
      - ปิดห่างจากทุกแนวเกิน NEAR_EMIT_BAND (= ไม่อยู่ในแนวพิจารณา)
    """
    s1, s2, r1, r2, ref_close = compute_dynamic_levels(daily)
    if ref_close is None:
        return None
    avwap = compute_avwap_5y(daily)

    levels = {"s1": s1, "s2": s2, "r1": r1, "r2": r2, "avwap5y": avwap}
    dist = {}
    nearest = None
    for k, v in levels.items():
        if v and v > 0:
            dp = round((ref_close - v) / v * 100, 2)
            dist[k] = dp
            if nearest is None or abs(dp) < abs(nearest[1]):
                nearest = (k, dp)

    if not nearest or abs(nearest[1]) > NEAR_EMIT_BAND:
        return None

    return {
        "symbol": symbol,
        "sector": sector,
        "close": round(ref_close, 2),
        "s1": s1, "s2": s2, "r1": r1, "r2": r2, "avwap5y": avwap,
        "dist": dist,                                   # signed % (ปิดเทียบแต่ละแนว)
        "nearest": {"level": nearest[0], "dist_pct": nearest[1]},
        "w_stage": w_stage,                             # บริบท stage รายสัปดาห์
        "setup": setup,                                 # "breakout" | "building" | None
        "signal": signal,                               # เช่น "D2+W2+M2"
        "reversal": _pick_reversal(reversal_rows),      # โครงกลับตัวที่ชัดสุด | None
    }
