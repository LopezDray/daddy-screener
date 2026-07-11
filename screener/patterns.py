#!/usr/bin/env python3
"""
Chart Pattern (reversal-only) — faithful port ของ chart-patterns.js — ห้ามแก้สูตรไม่ sync

พอร์ตเฉพาะ path ที่ "เรดาร์กลับตัว" (W3-11 Phase 3) ต้องใช้ — คืนเฉพาะ 4 keys กลับตัว:
    double_top · double_bottom · head_shoulders · inv_head_shoulders

⚠️ source of truth = ../../chart-patterns.js (repo หลัก DaddyInvestor)
   ค่าพารามิเตอร์ PATTERN_CFG / geometric rules / scoring ต้องตรง JS เป๊ะ
   → มี golden fixture parity test (tests/screener/test_patterns_parity.py) กัน drift
   แก้สูตรที่ chart-patterns.js ที่เดียว แล้ว re-port + regen fixture

Deterministic + reproducible (เป็น Tool ไม่ใช่ RAG): input เดียวกัน → output เท่ากันทุกครั้ง

consume candle shape ของ fetch_yahoo.py: {time, open, high, low, close, volume}
(detectors อ่านแค่ high/low/close/volume + index — ไม่พึ่ง key ชื่อ date/time)
"""

# ── พารามิเตอร์ต่อ TF (chart-patterns.js §PATTERN_CFG) — ต้องตรง JS เป๊ะ ──────────
PATTERN_CFG = {
    "1d":  {"lookback": 250, "W": 5, "minPct": 0.03, "volSMA": 20, "minBars": 80},
    "1wk": {"lookback": 156, "W": 3, "minPct": 0.05, "volSMA": 20, "minBars": 60},
    "1mo": {"lookback": 60,  "W": 2, "minPct": 0.08, "volSMA": 12, "minBars": 30},
}
# app ใช้ D/W/M — map ให้ตรง
TF_ALIAS = {"D": "1d", "W": "1wk", "M": "1mo", "1d": "1d", "1wk": "1wk", "1mo": "1mo"}

# keys กลับตัวที่เรดาร์สนใจ (mirror PATTERN_META ฝั่ง reversal)
REVERSAL_KEYS = {"double_top", "double_bottom", "head_shoulders", "inv_head_shoulders"}


def cfg_for(tf):
    return PATTERN_CFG[TF_ALIAS.get(tf, "1wk")]


# ── ATR14 (Wilder) — คืน scalar ล่าสุด ──────────────────────────────────────────
def compute_atr14(candles, period=14):
    n = len(candles)
    if n < period + 1:
        return None
    tr = []
    for i in range(1, n):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = 0.0
    for i in range(period):
        atr += tr[i]
    atr /= period
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
    return atr


# ── SMA ของ volume บนช่วง window ท้ายสุด (รอบ index อ้างอิง) ──
def vol_sma_at(candles, idx, window):
    total = 0.0
    cnt = 0
    for i in range(max(0, idx - window + 1), idx + 1):
        total += candles[i].get("volume") or 0
        cnt += 1
    return total / cnt if cnt else 0.0


# ── Fractal pivots + ZigZag filter (ATR/%) + บังคับสลับ H/L ──────────────────────
# คืน [{index, price, type:'H'|'L'}] เรียงตาม index · ยืนยันแล้วเท่านั้น
def find_pivots(candles, cfg, atr):
    n = len(candles)
    W = cfg["W"]
    raw = []
    for i in range(W, n - W):
        is_high = True
        is_low = True
        for j in range(i - W, i + W + 1):
            if j == i:
                continue
            if j < i:
                if candles[j]["high"] >= candles[i]["high"]:
                    is_high = False
                if candles[j]["low"] <= candles[i]["low"]:
                    is_low = False
            else:
                if candles[j]["high"] > candles[i]["high"]:
                    is_high = False
                if candles[j]["low"] < candles[i]["low"]:
                    is_low = False
        if is_high:
            raw.append({"index": i, "price": candles[i]["high"], "type": "H"})
        if is_low:
            raw.append({"index": i, "price": candles[i]["low"], "type": "L"})
    # เรียงตาม index; index เท่ากัน → H ก่อน L (mirror a.type==='H'?-1:1)
    raw.sort(key=lambda p: (p["index"], 0 if p["type"] == "H" else 1))

    # ZigZag: สลับ H/L + กรองขา swing เล็กกว่า threshold ทิ้ง
    out = []
    for p in raw:
        if not out:
            out.append(p)
            continue
        last = out[-1]
        if p["type"] != last["type"]:
            thr = max(1.5 * atr, cfg["minPct"] * last["price"])
            if abs(p["price"] - last["price"]) >= thr:
                out.append(p)
            # swing เล็กเกิน → ข้าม pivot รอง
        else:
            # ชนิดเดียวกันติดกัน → เก็บตัว extreme กว่า
            if (p["type"] == "H" and p["price"] > last["price"]) or \
               (p["type"] == "L" and p["price"] < last["price"]):
                out[-1] = p
    return out


# ── index แท่งล่าสุดที่ close "ข้าม" ระดับ trigger (จากล่าง→บน หรือ บน→ล่าง) ──
def last_cross_index(candles, level, direction):
    for i in range(len(candles) - 1, 0, -1):
        prev = candles[i - 1]["close"]
        cur = candles[i]["close"]
        if direction == "up" and prev <= level and cur > level:
            return i
        if direction == "down" and prev >= level and cur < level:
            return i
    return -1


# false-breakout: หลังทะลุที่ crossIdx มีแท่งปิดกลับเข้ากรอบภายใน bars แท่งไหม
def broke_back_within(candles, cross_idx, level, direction, bars=3):
    for i in range(cross_idx + 1, min(len(candles) - 1, cross_idx + bars) + 1):
        if direction == "up" and candles[i]["close"] < level:
            return True
        if direction == "down" and candles[i]["close"] > level:
            return True
    return False


# ── สถานะ breakout ร่วม (ใช้ทุก pattern ที่มี trigger line) ──
# คืน {status:'forming'|'confirmed'|'failed', volConfirmed:bool|None, crossIdx, testing}
def breakout_state(candles, level, direction, cfg, atr):
    n_last = len(candles) - 1
    buffer = 0.5 * atr
    trig = level + buffer if direction == "up" else level - buffer
    cross_idx = last_cross_index(candles, trig, direction)
    if cross_idx < 0:
        return {"status": "forming", "volConfirmed": None, "crossIdx": -1, "testing": False}
    if broke_back_within(candles, cross_idx, level, direction, 3):
        return {"status": "failed", "volConfirmed": None, "crossIdx": cross_idx, "testing": False}
    v_sma = vol_sma_at(candles, cross_idx, cfg["volSMA"])
    vol_confirmed = ((candles[cross_idx].get("volume") or 0) >= 1.3 * v_sma) if v_sma > 0 else None
    testing = cross_idx == n_last
    return {"status": "confirmed", "volConfirmed": vol_confirmed,
            "crossIdx": cross_idx, "testing": testing}


# ── least-squares fit เส้นตรงผ่านจุด pivot (x=index, y=price) → {slope, intercept} ──
def fit_line(points):
    n = len(points)
    if n < 2:
        return None
    sx = sy = sxy = sxx = 0.0
    for p in points:
        sx += p["x"]
        sy += p["y"]
        sxy += p["x"] * p["y"]
        sxx += p["x"] * p["x"]
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return {"slope": slope, "intercept": intercept}


def line_at(fit, x):
    return fit["slope"] * x + fit["intercept"]


# last cross ของ close กับ "เส้นเฉียง" line_fn(idx) (สำหรับ H&S neckline)
def last_cross_line(candles, line_fn, direction, buffer):
    for i in range(len(candles) - 1, 0, -1):
        lv_prev = line_fn(i - 1) + (buffer if direction == "up" else -buffer)
        lv = line_fn(i) + (buffer if direction == "up" else -buffer)
        prev = candles[i - 1]["close"]
        cur = candles[i]["close"]
        if direction == "up" and prev <= lv_prev and cur > lv:
            return i
        if direction == "down" and prev >= lv_prev and cur < lv:
            return i
    return -1


# ── scoring กลาง (chart-patterns.js §scoreParts) — base 50, cap 90 ──
def score_parts(parts):
    c = 50
    c += min(parts.get("touches", 0), 15)
    c += parts.get("fit", 0)
    c += parts.get("proportion", 0)
    c += parts.get("volume", 0)
    c += parts.get("confirmed", 0)
    return max(0, min(90, round(c)))


# ══ Detectors (reversal only) ═══════════════════════════════════════════════════

# P-DT/DB: Double Top / Double Bottom
def detect_double_top_bottom(candles, pivots, atr, cfg):
    price = candles[-1]["close"]
    tf = TF_ALIAS.get(cfg.get("_tf"), "1wk")
    min_sep = {"1d": 10, "1wk": 5, "1mo": 3}.get(tf, 5)
    results = []

    # Double Top: 2 pivot H ท้าย + trough (pivot L) คั่นกลาง
    highs = [p for p in pivots if p["type"] == "H"]
    if len(highs) >= 2:
        P1, P2 = highs[-2], highs[-1]
        mid = (P1["price"] + P2["price"]) / 2
        troughs = sorted(
            [p for p in pivots if p["type"] == "L" and P1["index"] < p["index"] < P2["index"]],
            key=lambda p: p["price"])
        trough = troughs[0] if troughs else None
        if trough and \
           abs(P1["price"] - P2["price"]) <= max(0.75 * atr, 0.015 * mid) and \
           (P2["index"] - P1["index"]) >= min_sep and \
           (mid - trough["price"]) >= max(3 * atr, 0.05 * mid):
            neck = trough["price"]
            brk = breakout_state(candles, neck, "down", cfg, atr)
            confidence = score_parts({
                "touches": 4,
                "proportion": 10 if (P2["index"] - P1["index"]) >= min_sep * 1.5 else 5,
                "fit": 10 if abs(P1["price"] - P2["price"]) <= 0.4 * atr else 4,
                "volume": 10 if brk["volConfirmed"] else 0,
                "confirmed": 10 if brk["status"] == "confirmed" else 0,
            })
            results.append({
                "key": "double_top",
                "bias": "neutral" if brk["status"] == "failed" else "down",
                "status": brk["status"],
                "confidence": confidence,
                "volConfirmed": brk["volConfirmed"],
            })

    # Double Bottom: 2 pivot L ท้าย + peak คั่นกลาง
    lows = [p for p in pivots if p["type"] == "L"]
    if len(lows) >= 2:
        P1, P2 = lows[-2], lows[-1]
        mid = (P1["price"] + P2["price"]) / 2
        peaks = sorted(
            [p for p in pivots if p["type"] == "H" and P1["index"] < p["index"] < P2["index"]],
            key=lambda p: -p["price"])
        peak = peaks[0] if peaks else None
        if peak and \
           abs(P1["price"] - P2["price"]) <= max(0.75 * atr, 0.015 * mid) and \
           (P2["index"] - P1["index"]) >= min_sep and \
           (peak["price"] - mid) >= max(3 * atr, 0.05 * mid):
            neck = peak["price"]
            brk = breakout_state(candles, neck, "up", cfg, atr)
            confidence = score_parts({
                "touches": 4,
                "proportion": 10 if (P2["index"] - P1["index"]) >= min_sep * 1.5 else 5,
                "fit": 10 if abs(P1["price"] - P2["price"]) <= 0.4 * atr else 4,
                "volume": 10 if brk["volConfirmed"] else 0,
                "confirmed": 10 if brk["status"] == "confirmed" else 0,
            })
            results.append({
                "key": "double_bottom",
                "bias": "neutral" if brk["status"] == "failed" else "up",
                "status": brk["status"],
                "confidence": confidence,
                "volConfirmed": brk["volConfirmed"],
            })
    return results


# P-HS: Head & Shoulders / Inverse — 5 pivot เรียง H-L-H-L-H (หรือ mirror)
def detect_head_shoulders(candles, pivots, atr, cfg):
    if len(pivots) < 5:
        return None
    p5 = pivots[-5:]
    types = "".join(p["type"] for p in p5)
    before = pivots[-6] if len(pivots) >= 6 else None

    if types == "HLHLH":
        H1, L1, H2, L2, H3 = p5
        # หัว (H2) สูงกว่าไหล่ ≥1×ATR · ไหล่ 2 ข้างสมมาตร ≤1.5×ATR
        if H2["price"] - max(H1["price"], H3["price"]) < atr:
            return None
        if abs(H1["price"] - H3["price"]) > 1.5 * atr:
            return None
        # context: ต้องมาจากขาขึ้น (pivot ก่อนไหล่ซ้ายต่ำกว่า H1)
        if before and before["price"] >= H1["price"]:
            return None
        neck = fit_line([{"x": L1["index"], "y": L1["price"]},
                         {"x": L2["index"], "y": L2["price"]}])
        if not neck or abs(neck["slope"]) > 0.1 * atr:
            return None
        neck_fn = lambda i: line_at(neck, i)
        cross = last_cross_line(candles, neck_fn, "down", 0.5 * atr)
        return _hs_result(candles, atr, cfg, p5, neck_fn, cross, "down", False)

    if types == "LHLHL":
        L1, H1, L2, H2, L3 = p5
        if min(L1["price"], L3["price"]) - L2["price"] < atr:
            return None
        if abs(L1["price"] - L3["price"]) > 1.5 * atr:
            return None
        if before and before["price"] <= L1["price"]:
            return None
        neck = fit_line([{"x": H1["index"], "y": H1["price"]},
                         {"x": H2["index"], "y": H2["price"]}])
        if not neck or abs(neck["slope"]) > 0.1 * atr:
            return None
        neck_fn = lambda i: line_at(neck, i)
        cross = last_cross_line(candles, neck_fn, "up", 0.5 * atr)
        return _hs_result(candles, atr, cfg, p5, neck_fn, cross, "up", True)

    return None


def _hs_result(candles, atr, cfg, p5, neck_fn, cross, direction, inverse):
    status = "forming"
    bias = "up" if inverse else "down"
    vol_confirmed = None
    if cross >= 0:
        if broke_back_within(candles, cross, neck_fn(cross), direction, 3):
            status = "failed"
            bias = "neutral"
        else:
            status = "confirmed"
            v_sma = vol_sma_at(candles, cross, cfg["volSMA"])
            vol_confirmed = ((candles[cross].get("volume") or 0) >= 1.3 * v_sma) if v_sma > 0 else None
    confidence = score_parts({
        "touches": 6,
        "fit": 10,
        "proportion": 8,
        "volume": 10 if vol_confirmed else 0,
        "confirmed": 10 if status == "confirmed" else 0,
    })
    base = "inv_head_shoulders" if inverse else "head_shoulders"
    return {
        "key": base,
        "bias": bias,
        "status": status,
        "confidence": confidence,
        "volConfirmed": vol_confirmed,
    }


# ── entry point ─────────────────────────────────────────────────────────────────
# detect_reversals(candles, tf) → {tf, atr, enough, patterns:[{key,bias,status,confidence,volConfirmed}]}
# คืนเฉพาะ 4 keys กลับตัว · ข้อมูลไม่พอ → {enough:False, patterns:[]}
def detect_reversals(candles, tf):
    cfg = dict(cfg_for(tf))
    cfg["_tf"] = TF_ALIAS.get(tf, "1wk")
    clean = [c for c in (candles or [])
             if c and c.get("open") and c.get("high") and c.get("low") and c.get("close")]
    scoped = clean[-cfg["lookback"]:]
    if len(scoped) < cfg["minBars"]:
        return {"tf": tf, "atr": None, "enough": False, "patterns": []}
    atr = compute_atr14(scoped, 14)
    if not atr or atr <= 0:
        return {"tf": tf, "atr": None, "enough": False, "patterns": []}
    pivots = find_pivots(scoped, cfg, atr)

    patterns = []
    patterns.extend(detect_double_top_bottom(scoped, pivots, atr, cfg))
    hs = detect_head_shoulders(scoped, pivots, atr, cfg)
    if hs:
        patterns.append(hs)

    # เรียง: confirmed ก่อน forming ก่อน failed · ในกลุ่มเดียวกัน confidence สูงก่อน
    rank = {"confirmed": 0, "forming": 1, "failed": 2}
    patterns.sort(key=lambda p: (rank.get(p["status"], 3), -p["confidence"]))
    return {"tf": tf, "atr": atr, "enough": True, "patterns": patterns}
