#!/usr/bin/env python3
"""
Breakout + DCA scoring engine
รวม Stage Analysis + Volume Profile + Breakout + RS → คะแนนเดียว 0-100 + เกรด A/B

Contract อ้างอิง: SCREENER_DESIGN (spec ในดีไซน์) — hard gates G1-G5, breakout B1-B3,
soft filters S1-S4, scoring model. quality_pct = None (ให้ frontend enrich จาก Supabase)
"""

from statistics import mean

from .stage import analyze_stage, get_signal, MA_PERIOD
from .volume_profile import compute_volume_profile

# ── ค่าคงที่/threshold (จูนที่นี่ที่เดียว) ──────────────────────────────────────
W_STAGE2_MIN_CONF = 60          # G1
MIN_WEEKLY_BARS = 60            # G5
MIN_PRICE = 5.0                # G4
MIN_DOLLAR_VOL = 10_000_000    # G4 (avg 20d close*vol)
BASE_LOOKBACK = 30             # สัปดาห์ย้อนหลังของ "ฐาน"
BASE_SKIP_RECENT = 4           # ตัด n สัปดาห์ล่าสุด (ขา breakout) ออกจากฐาน
VP_LOOKBACK = 56               # สัปดาห์สำหรับคำนวณ Volume Profile ของฐาน
VOL_CONFIRM = 1.5             # B3: vol สัปดาห์ล่าสุด ≥ x เท่าของ avg 10 สัปดาห์
GRADE_A = 80
GRADE_B = 65

INDEX_FOR = {"nasdaq100": "QQQ", "sp500": "SPY", "russell2000": "IWM"}


def evaluate(symbol, daily, weekly, monthly, index_weekly, universe, sector=None):
    """
    คืน row dict (ผ่าน gate + เกรด ≥ B) หรือ None
    daily/weekly/monthly = list ของ candle {open,high,low,close,volume,time}
    index_weekly = candle รายสัปดาห์ของดัชนีแม่ (QQQ/SPY/IWM)
    """
    # ── HARD GATES ──────────────────────────────────────────────────────────
    if len(weekly) < MIN_WEEKLY_BARS:
        return None

    w = analyze_stage(weekly, MA_PERIOD["1wk"], "1wk")
    if not w or w["stage"] != 2 or w["confidence"] < W_STAGE2_MIN_CONF:
        return None                                             # G1
    if not (w["price_vs_ma"] > 0 and w["slope4"] > 0):
        return None                                             # G3

    m = analyze_stage(monthly, MA_PERIOD["1mo"], "1mo") if len(monthly) >= 12 else None
    m_stage = m["stage"] if m else None
    if m_stage is not None and m_stage not in (1, 2):
        return None                                             # G2 (ห้าม 3/4)

    price = weekly[-1]["close"]
    if price < MIN_PRICE:
        return None                                             # G4
    recent_daily = daily[-20:] if len(daily) >= 20 else daily
    avg_dollar_vol = mean(c["close"] * c["volume"] for c in recent_daily) if recent_daily else 0
    if avg_dollar_vol < MIN_DOLLAR_VOL:
        return None                                             # G4

    d = analyze_stage(daily, MA_PERIOD["1d"], "1d") if len(daily) >= 160 else None
    d_stage = d["stage"] if d else None

    # ── BREAKOUT (B1/B2/B3) ─────────────────────────────────────────────────
    base = weekly[-BASE_LOOKBACK:-BASE_SKIP_RECENT] if len(weekly) >= BASE_LOOKBACK else weekly[:-BASE_SKIP_RECENT]
    if len(base) < 8:
        return None
    base_high = max(c["high"] for c in base)

    vp_base = weekly[-VP_LOOKBACK:-BASE_SKIP_RECENT] if len(weekly) >= VP_LOOKBACK else weekly[:-BASE_SKIP_RECENT]
    vp = compute_volume_profile(vp_base, n_bins=40, close=price)

    passed_b1 = price > base_high
    passed_b2 = bool(vp and price > vp["vah"])
    fresh_bars = _fresh_bars(weekly, base_high)                 # สัปดาห์ที่ยืนเหนือ pivot ต่อเนื่อง

    # vol confirmation (B3): วัด volume ที่ "แท่ง breakout" ไม่ใช่แท่งล่าสุด
    # (breakout อาจเกิดหลายสัปดาห์ก่อน → แท่งล่าสุด = consolidation vol ต่ำ ไม่สะท้อน conviction)
    vol_ratio = _breakout_volume_ratio(weekly, base_high)
    if vol_ratio is None:                                       # ยังไม่ทะลุ → ใช้ vol ต่อเนื่องล่าสุดเป็น context
        vols = [c["volume"] for c in weekly]
        avg10 = mean(vols[-11:-1]) if len(vols) >= 11 and mean(vols[-11:-1]) > 0 else 0
        vol_ratio = round(vols[-1] / avg10, 2) if avg10 > 0 else 0

    # setup = 2 หมวด: 🚀 breakout (close ทะลุ base high แล้ว) vs 🌱 building (Stage 2 ยังต่ำกว่าจุดเบรก)
    setup = "breakout" if passed_b1 else "building"
    if passed_b1 and passed_b2:
        btype = "VAH+base"
    elif passed_b1:
        btype = "base"
    elif passed_b2:
        btype = "VAH"          # building แต่ยืนเหนือ value area แล้ว
    else:
        btype = None
    # dist จากจุดเบรก (base_high): +เหนือ = breakout · −ต่ำกว่า = ยังไต่อยู่ (อ่านคู่กับ setup)
    dist_pct = round((price - base_high) / base_high * 100, 2) if base_high > 0 else 0

    # up vs down volume ในฐาน (สะสมจริงไหม)
    up_vol = sum(c["volume"] for c in base if c["close"] >= c["open"])
    dn_vol = sum(c["volume"] for c in base if c["close"] < c["open"])
    up_vs_down = round(up_vol / dn_vol, 2) if dn_vol > 0 else (9.99 if up_vol > 0 else 1.0)

    # ── RS เทียบดัชนีแม่ (S1) ────────────────────────────────────────────────
    rs = _relative_strength(weekly, index_weekly)

    # ── SCORING ─────────────────────────────────────────────────────────────
    score = 0.0
    full_base = len(base) >= (BASE_LOOKBACK - BASE_SKIP_RECENT)

    # Trend (40) — เหมือนกันทั้ง 2 หมวด
    score += round(25 * (w["confidence"] / 100.0), 1)
    if m_stage == 2:   score += 10
    elif m_stage == 1: score += 5
    if d_stage == 2:   score += 5

    # Structure (25) — คนละเกณฑ์ตาม setup
    if setup == "breakout":
        if fresh_bars is not None and fresh_bars <= 2:   score += 10   # เพิ่งเบรก
        elif fresh_bars is not None and fresh_bars <= 5: score += 6
        score += 10 if (passed_b1 and passed_b2) else 6                # ทะลุทั้ง base+VAH
        if full_base: score += 5
    else:  # building — ยิ่งใกล้จุดเบรก + ยืนเหนือ value area ยิ่งพร้อม
        near = -dist_pct                                              # ระยะต่ำกว่าจุดเบรก (บวก)
        if near <= 5:    score += 10                                  # ขดใต้แนวต้าน พร้อมเบรก
        elif near <= 12: score += 6
        if passed_b2: score += 6                                      # ยืนเหนือ VAH
        if full_base: score += 5

    # Volume (20)
    if setup == "breakout":
        if vol_ratio >= 2.5:           score += 12                    # วอลุ่มเบรกแรง
        elif vol_ratio >= VOL_CONFIRM: score += 8
    if up_vs_down > 1: score += 8                                     # สะสมจริง (up-week vol > down-week)

    # Volume Profile (15)
    if vp:
        overhead = vp["overhead_supply_pct"]
        if setup == "breakout":
            if overhead < 20: score += 8                             # เหนือหัวโล่ง
            if 0 <= dist_pct <= 10: score += 7                        # ไม่ไล่ราคา
        else:  # building — room เหนือหัว + ราคายังอยู่ในโซนออม (VAL–POC)
            if overhead < 30: score += 8
            if vp["val"] <= price <= vp["poc"]: score += 7           # ของถูกในโซนสะสม
            elif price <= vp["vah"]:            score += 4

    # Penalty — เฉพาะ breakout ที่วิ่งไกลจากจุดเบรก (building ไม่โดน — ต่ำกว่าจุดเบรกอยู่แล้ว)
    if setup == "breakout" and dist_pct > 15: score -= 10

    # RS bonus (S1 — เข้าคะแนน ไม่ตกรอบ)
    if rs and rs.get("rs_new_high"): score += 3
    if rs and rs.get("rs_12w", 0) > 0: score += 2

    score = max(0, min(100, round(score)))
    if score < GRADE_B:
        return None
    grade = "A" if score >= GRADE_A else "B"

    return {
        "symbol": symbol,
        "sector": sector,
        "also_in": [],                       # เติมทีหลังตอน merge ข้าม universe
        "score": score,
        "grade": grade,
        "signal": get_signal(d_stage, w["stage"], m_stage),
        "price": round(price, 2),
        "setup": setup,                      # "breakout" 🚀 | "building" 🌱 → frontend แยกหมวด
        "breakout": {
            "type": btype,
            "pivot": round(base_high, 2),    # ราคาจุดเบรก (base high 26w)
            "dist_pct": dist_pct,            # +เหนือจุดเบรก(breakout) / −ต่ำกว่า(building)
            "fresh_bars": fresh_bars,
        },
        "volume": {"ratio": vol_ratio, "up_vs_down": up_vs_down},
        "vp": None if not vp else {
            "poc": vp["poc"], "val": vp["val"], "vah": vp["vah"],
            "overhead_supply_pct": vp["overhead_supply_pct"],
        },
        "trend": {
            "d_stage": d_stage, "w_stage": w["stage"], "m_stage": m_stage,
            "w_conf": w["confidence"], "w_slope4": w["slope4"],
        },
        "rs": None if not rs else {"vs_index": INDEX_FOR.get(universe), **rs},
        "quality_pct": None,                 # frontend enrich จาก factor_percentiles
        "dca_zone": None if not vp else {"low": vp["val"], "high": vp["poc"]},
    }


def _breakout_volume_ratio(weekly, base_high, window=10):
    """
    หา "แท่ง breakout" (สัปดาห์แรกของ run ปัจจุบันที่ close ทะลุ base_high)
    แล้ววัด volume เทียบ avg ของ window สัปดาห์ก่อนหน้า
    คืน None ถ้ายังไม่ทะลุ (จะได้ไปใช้ vol context แทน)
    """
    n = len(weekly)
    closes = [c["close"] for c in weekly]
    if not closes or closes[-1] <= base_high:
        return None
    bo_idx = n - 1
    for i in range(n - 1, -1, -1):
        if closes[i] > base_high:
            bo_idx = i
        else:
            break
    prior = [weekly[j]["volume"] for j in range(max(0, bo_idx - window), bo_idx)]
    avg = mean(prior) if prior else 0
    if avg <= 0:
        return None
    return round(weekly[bo_idx]["volume"] / avg, 2)


def _fresh_bars(weekly, base_high):
    """จำนวนสัปดาห์ที่ close ยืนเหนือ pivot ต่อเนื่องล่าสุด (None = ยังไม่ทะลุ)"""
    closes = [c["close"] for c in weekly]
    if not closes or closes[-1] <= base_high:
        return None
    bars = 0
    for c in reversed(closes):
        if c > base_high:
            bars += 1
        else:
            break
    return bars


def _relative_strength(weekly, index_weekly, window=13):
    """RS = ratio ราคา/ดัชนี · คืน {rs_12w (%), rs_new_high} หรือ None"""
    if len(weekly) < window or len(index_weekly) < window:
        return None
    sc = [c["close"] for c in weekly[-window:]]
    ic = [c["close"] for c in index_weekly[-window:]]
    rs = [s / i for s, i in zip(sc, ic) if i > 0]
    if len(rs) < window:
        return None
    change = (rs[-1] / rs[0] - 1) * 100 if rs[0] else 0
    return {"rs_12w": round(change, 2), "rs_new_high": rs[-1] >= max(rs) * 0.999}
