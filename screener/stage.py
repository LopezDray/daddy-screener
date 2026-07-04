#!/usr/bin/env python3
"""
Stan Weinstein Stage Analysis — port ตรงจาก DaddyInvestor scan_nasdaq_screener.py
(mirror ของ stage-analysis.html analyzeStage) เพื่อให้ผลตรงกับเว็บหลักเป๊ะ

ห้ามแก้สูตร analyze_stage() โดยไม่ sync กับ repo หลัก — เป็น faithful port
"""

MA_PERIOD = {"1d": 150, "1wk": 30, "1mo": 10}
MIN_CANDLES = {"1d": 160, "1wk": 35, "1mo": 12}


def analyze_stage(candles, ma_period, tf):
    """คืน dict {stage, confidence, price_vs_ma, slope4, pos_range} หรือ None ถ้าข้อมูลไม่พอ"""
    n = len(candles)
    if n < ma_period + 10:
        return None

    closes = [c["close"] for c in candles]

    # SMA
    ma = []
    for i in range(ma_period - 1, n):
        ma.append(sum(closes[i - ma_period + 1: i + 1]) / ma_period)

    current_ma = ma[-1]
    prev_ma4 = ma[-5] if len(ma) >= 5 else ma[0]
    prev_ma8 = ma[-9] if len(ma) >= 9 else ma[0]
    current_close = closes[-1]

    slope4 = (current_ma - prev_ma4) / prev_ma4 * 100 if prev_ma4 else 0
    slope8 = (current_ma - prev_ma8) / prev_ma8 * 100 if prev_ma8 else 0
    price_vs_ma = (current_close - current_ma) / current_ma * 100 if current_ma else 0

    lookback = min({"1mo": 12, "1d": 252}.get(tf, 52), n)
    recent = candles[-lookback:]
    high52 = max(c["high"] for c in recent)
    low52 = min(c["low"] for c in recent)
    range52 = high52 - low52
    pos_range = (current_close - low52) / range52 * 100 if range52 > 0 else 50

    above_ma = price_vs_ma > 0
    ma_rising = slope4 > 0.25
    ma_falling = slope4 < -0.25
    ma_flat = not ma_rising and not ma_falling

    if above_ma and ma_rising:
        stage = 2
        c = 55
        if slope4 > 0.5: c += 7
        if slope4 > 2.0: c += 6
        if slope4 > 5.0: c += 5
        if slope8 > 0.5: c += 5
        if slope8 > 2.0: c += 4
        if slope4 > slope8 > 0: c += 4
        if price_vs_ma > 5:  c += 5
        if price_vs_ma > 15: c += 4
        if pos_range > 70: c += 7
        if pos_range > 85: c += 5
        confidence = min(c, 95)

    elif not above_ma and ma_falling:
        stage = 4
        c = 55
        if slope4 < -0.5: c += 7
        if slope4 < -2.0: c += 6
        if slope4 < -5.0: c += 5
        if slope8 < -0.5: c += 5
        if slope8 < -2.0: c += 4
        if slope4 < slope8 < 0: c += 4
        if price_vs_ma < -5:  c += 5
        if price_vs_ma < -15: c += 4
        if pos_range < 30: c += 7
        if pos_range < 15: c += 5
        confidence = min(c, 95)

    elif ma_flat or (not above_ma and ma_rising) or (above_ma and ma_falling):
        if pos_range <= 50:
            stage = 1
            c = 42
            if ma_flat:                c += 18
            if pos_range < 30:         c += 16
            if abs(price_vs_ma) < 5:   c += 14
            confidence = min(c, 88)
        else:
            stage = 3
            c = 42
            if ma_flat and pos_range > 65:  c += 20
            if above_ma and ma_falling:     c += 18
            if pos_range > 75:              c += 12
            confidence = min(c, 88)
    else:
        stage = 2 if above_ma else 4
        confidence = 38

    return {"stage": stage, "confidence": confidence,
            "price_vs_ma": round(price_vs_ma, 2), "slope4": round(slope4, 2),
            "pos_range": round(pos_range, 1)}


def get_signal(d, w, m):
    """multi-timeframe confluence label (เหมือน repo หลัก)"""
    if d == 2 and w == 2 and m == 2:
        return "D2+W2+M2"
    if d == 1 and w == 2 and m == 2:
        return "D1+W2+M2"
    if d == 2 and w == 2 and m == 1:
        return "D2+W2+M1"
    if d == 2 and w == 1 and m == 2:
        return "D2+W1+M2"
    if w == 2 and m == 2:
        return "W2+M2"
    if d == 2 and w == 2:
        return "D2+W2"
    return None


SIGNAL_RANK = {
    "D2+W2+M2": 1,
    "D1+W2+M2": 2,
    "D2+W2+M1": 3,
    "D2+W1+M2": 4,
    "W2+M2":    5,
    "D2+W2":    6,
}
