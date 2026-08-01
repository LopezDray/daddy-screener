#!/usr/bin/env python3
"""
daddy-screener — Elliott "กำลังเดินคลื่น" (partial count) สำหรับ scan ทั้งตลาด

โจทย์: แผง Elliott ในแอปตอบได้ทีละตัว → ตัวนี้ไล่ทั้ง universe แล้วบอกว่า
"ตอนนี้หุ้นตัวไหนนับได้ถึงคลื่นไหนแล้ว (ยังไม่ครบ 5)" เพื่อทำชิป 🌊 บนหน้า Universe

⚠️ ข้อจำกัดที่ต้องพูดตรงๆ ทุกครั้งที่แสดงผล (กติกาเดียวกับ chart-patterns.js/elliott-panel.js):
  - นี่คือ "นิยามหนึ่ง" ของ Elliott Wave — การนับของนักวิเคราะห์เป็น discretionary
  - สถิติโครงสร้างเชิงการศึกษา ไม่ใช่ win-rate / คำแนะนำเทรด / entry-SL-TP
  - อัตรารอดจนครบ 5 คลื่น (วัด 686 หุ้น 07-29): ขั้น 1-2-3 = 12.2% · ขั้น 1-2 = 7.9%
    → **ไม่ label ขั้น 1-2 เลย** (อ่อนเกินกว่าจะขึ้นจอ) · ขั้น 1-2-3-4 คือขั้นที่เชื่อได้มากสุด
  - 📅 ป้ายต้องกำกับวันที่เสมอ — สถานะพลิกวันต่อวัน (SNOW 07-28 pivot ใหม่ทำ 1-2-3-4 หายทั้งชุด)

🔁 พอร์ตตรงจาก DaddyInvestor/scripts/elliott_wave_core.py + elliott_wave5_test.py
   (ซึ่ง parity กับ chart-elliott.js ผ่าน tests/elliott_parity.mjs)
   **แก้สูตรที่นี่ = ต้องแก้ทั้ง 3 ฝั่ง** (core.py · chart-elliott.js · ไฟล์นี้)

หลักกัน look-ahead/repaint (เหมือน core เป๊ะ):
  - threshold ZigZag ใช้ ATR **ณ เวลาของ pivot** ไม่ใช่ ATR ตัวเดียวจาก series เต็ม
    (ATR ตัวเดียวทำให้เกณฑ์ถูกแก้ย้อนหลัง → โครงสร้างที่เคยเจอหายไป)
  - ทุก pivot ที่นับต้อง lock ได้จริง (lock_index) = แท่งแรกที่ ZigZag real-time จะ commit

stdlib ล้วน · ไม่แตะ network · CPU อย่างเดียว (Yahoo 0 call เพิ่ม — reuse candles ของ scan)
self-test: python -m screener.elliott --self-test     # $0
"""

from screener.patterns import PATTERN_CFG, TF_ALIAS

ATR_MULT = 1.5                 # คงที่ = parity กับ production (chart-elliott.js)

# นับว่า "ยังเดินอยู่" ได้ไม่เกินกี่แท่งหลัง pivot ล่าสุด lock — เกินนี้ = ค้างเก่า ไม่ใช่สถานะปัจจุบัน
# 120 แท่งรายวัน ≈ 6 เดือน · ค่าเดียวกับ TIMEOUT_BARS["daily"] ของ elliott_wave_core
MAX_AGE_BARS = 120


def cfg_for(tf):
    c = PATTERN_CFG[TF_ALIAS.get(tf, "1d")]
    return {"W": c["W"], "minPct": c["minPct"]}


def compute_atr_series(candles, period=14):
    """ATR แบบ "ณ เวลานั้น" — out[i] = ATR จากแท่ง 0..i เท่านั้น
    ต้องตรงกับ elliott_wave_core.compute_atr_series / chart-elliott.js::computeATRSeries เป๊ะ"""
    n = len(candles)
    out = [None] * n
    if n < period + 1:
        return out
    tr = []
    for i in range(1, n):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(tr[:period]) / period
    out[period] = atr
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
        out[i + 1] = atr
    return out


def atr_at(atr_series, i):
    """ATR ที่ "รู้ได้" ณ แท่ง i · ก่อนหน้านั้นยังคำนวณไม่ได้ → ใช้ตัวแรกที่มี"""
    if i < len(atr_series) and atr_series[i] is not None:
        return atr_series[i]
    for j in range(min(i, len(atr_series) - 1), -1, -1):
        if atr_series[j] is not None:
            return atr_series[j]
    for v in atr_series:
        if v is not None:
            return v
    return None


def find_pivots(candles, cfg, atr_series):
    """Fractal pivots + ZigZag — รูปทรง fractal ตรง patterns.find_pivots
    ต่างที่ threshold ใช้ ATR ณ เวลาของ pivot (ดู compute_atr_series)"""
    n, W = len(candles), cfg["W"]
    raw = []
    for i in range(W, n - W):
        is_high = is_low = True
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
    raw.sort(key=lambda p: (p["index"], 0 if p["type"] == "H" else 1))

    out = []
    for p in raw:
        if not out:
            out.append(p)
            continue
        last = out[-1]
        if p["type"] != last["type"]:
            thr = max(ATR_MULT * (atr_at(atr_series, p["index"]) or 0.0),
                      cfg["minPct"] * last["price"])
            if abs(p["price"] - last["price"]) >= thr:
                out.append(p)
        elif (p["type"] == "H" and p["price"] > last["price"]) or \
             (p["type"] == "L" and p["price"] < last["price"]):
            out[-1] = p
    return out


def lock_index(candles, pivot, cfg, atr_series):
    """แท่งแรกที่ ZigZag real-time จะ commit pivot นี้ = แท่ง j >= index+W ที่
    excursion ฝั่งตรงข้ามจากราคา pivot >= threshold · คืน None ถ้าไม่เคย lock"""
    thr = max(ATR_MULT * (atr_at(atr_series, pivot["index"]) or 0.0),
              cfg["minPct"] * pivot["price"])
    for j in range(pivot["index"] + cfg["W"], len(candles)):
        if pivot["type"] == "H":
            if pivot["price"] - candles[j]["low"] >= thr:
                return j
        else:
            if candles[j]["high"] - pivot["price"] >= thr:
                return j
    return None


def _check_1234(five):
    """5 pivot ติดกัน → sgn ถ้าเป็น 1-2-3-4 ที่ผ่านกติกา (R1/R2/R4 + คลื่นเป็นบวก) · ไม่งั้น None
    mirror elliott_wave5_test.find_partial_1234 (R3 ตรวจได้แค่บางส่วน — คลื่น 5 ยังไม่เกิด)"""
    types = "".join(p["type"] for p in five)
    if types == "LHLHL":
        sgn = 1
    elif types == "HLHLH":
        sgn = -1
    else:
        return None
    p0, p1, p2, p3, p4 = (p["price"] for p in five)
    if sgn * (p1 - p0) <= 0 or sgn * (p3 - p2) <= 0:      # w1/w3 ต้องเป็นบวก
        return None
    if not (sgn * (p2 - p0) > 0):      # R1 — W2 retrace ไม่ถึง 100% ของ W1
        return None
    if not (sgn * (p3 - p1) > 0):      # R2 — W3 ทำ new extreme
        return None
    if not (sgn * (p4 - p1) > 0):      # R4 — W4 ไม่เข้าเขต W1 (strict)
        return None
    return sgn


def _check_123(four):
    """4 pivot ติดกัน → sgn ถ้าเป็น 1-2-3 ที่ผ่านกติกา · ไม่งั้น None
    mirror elliott_wave5_test.find_partial_123 / chart-elliott.js::findPartial123"""
    types = "".join(p["type"] for p in four)
    if types == "LHLH":
        sgn = 1
    elif types == "HLHL":
        sgn = -1
    else:
        return None
    p0, p1, p2, p3 = (p["price"] for p in four)
    if sgn * (p1 - p0) <= 0 or sgn * (p3 - p2) <= 0:
        return None
    if not (sgn * (p2 - p0) > 0):      # R1
        return None
    if not (sgn * (p3 - p1) > 0):      # R2
        return None
    return sgn


def _still_alive(candles, from_index, wave1_price, sgn):
    """หลังจาก pivot ล่าสุด ราคายัง "ไม่ทำลายการนับ" อยู่ไหม

    เส้นตายเดียวกับ R4: คลื่น 4 ห้ามเข้าเขตคลื่น 1 → ขาขึ้นต้องไม่มีแท่งไหน low หลุดยอดคลื่น 1
    (ขาลงกลับด้าน) · หลุด = การนับชุดนี้ตาย ไม่ควรขึ้นป้าย
    ⚠️ ตรวจถึงแท่งสุดท้ายจริง — pivot ล่าสุดอยู่ห่างปลาย >= W แท่งเสมอ (fractal ต้องการ W ข้างขวา)
       ช่วงหางนั้นยังไม่มี pivot ใหม่ แต่ราคาเดินไปแล้ว → ถ้าไม่ตรงนี้ป้ายจะค้างของตาย"""
    for j in range(from_index + 1, len(candles)):
        px = candles[j]["low"] if sgn > 0 else candles[j]["high"]
        if sgn * (px - wave1_price) <= 0:
            return False
    return True


def current_partial(candles, tf="1d", max_age_bars=MAX_AGE_BARS):
    """สถานะ "กำลังเดินคลื่น" ของ series นี้ ณ แท่งสุดท้าย · คืน dict หรือ None

    อ่านจาก **หาง ZigZag** (pivot ล่าสุด) เพราะคำถามคือ "ตอนนี้อยู่ขั้นไหน" ไม่ใช่
    "เคยมีขั้นไหนบ้าง" · ลอง 1-2-3-4 ก่อน (ขั้นที่เชื่อได้มากสุด) แล้วค่อยถอยมา 1-2-3

    คืน {"stage": 3|4, "direction": "bull"|"bear", "code": "3u"/"4u"/"3d"/"4d",
         "lock_index": int, "age_bars": int, "pivot_index": int}

    เงื่อนไขที่ต้องผ่านครบ:
      1. รูปทรง + กติกา R1/R2(/R4) ผ่าน
      2. pivot ตัวสุดท้าย **lock ได้จริง** (ZigZag real-time commit แล้ว — ไม่ใช่ของที่เห็นย้อนหลัง)
      3. ราคาหลังจากนั้นยังไม่ทำลายการนับ (_still_alive)
      4. ยังสด — lock ห่างแท่งสุดท้ายไม่เกิน max_age_bars
    """
    cfg = cfg_for(tf)
    if len(candles) < cfg["W"] * 2 + 20:
        return None
    ats = compute_atr_series(candles)
    pivots = find_pivots(candles, cfg, ats)
    last = len(candles) - 1

    for stage, need, check in ((4, 5, _check_1234), (3, 4, _check_123)):
        if len(pivots) < need:
            continue
        tail = pivots[-need:]
        sgn = check(tail)
        if sgn is None:
            continue
        lk = lock_index(candles, tail[-1], cfg, ats)
        if lk is None:                       # ยัง commit ไม่ได้ = real-time ยังไม่เห็น
            continue
        age = last - lk
        if age > max_age_bars:               # ค้างเก่า ไม่ใช่สถานะปัจจุบัน
            continue
        if not _still_alive(candles, tail[-1]["index"], tail[1]["price"], sgn):
            continue
        direction = "bull" if sgn > 0 else "bear"
        return {
            "stage": stage,
            "direction": direction,
            "code": f"{stage}{'u' if sgn > 0 else 'd'}",
            "lock_index": lk,
            "age_bars": age,
            "pivot_index": tail[-1]["index"],
        }
    return None


def wave_code(candles, tf="1d"):
    """ค่าที่ลงคอลัมน์ `ew` ของ us-all-table.json — "3u"/"4u"/"3d"/"4d" หรือ None"""
    res = current_partial(candles, tf)
    return res["code"] if res else None


# ── self-test ($0 ไม่แตะ net) ────────────────────────────────────────────────
def _mk(seq):
    """สร้าง candle จาก list ราคา — high/low กาง ±0.5% กัน ATR = 0"""
    out = []
    for p in seq:
        out.append({"open": p, "high": p * 1.005, "low": p * 0.995,
                    "close": p, "volume": 1_000_000})
    return out


def _leg(a, b, n):
    """ขาเดินราคาแบบเชิงเส้น a → b จำนวน n แท่ง (ไม่รวมจุดเริ่ม)"""
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def _base_123(w3_top=175.0):
    """ท่อนต้นร่วม: ลงมาทำจุดต่ำ L0 → W1 → W2 → W3
    ⚠️ ต้องมีขาลงนำก่อน L0 — ราคานิ่งไม่เกิด fractal low (เงื่อนไข <= ในการเทียบซ้าย)"""
    return (_leg(115, 100, 20)              # ลงมาทำจุดต่ำ = L0
            + _leg(100, 130, 25)            # W1 → ยอด 130
            + _leg(130, 112, 20)            # W2 → ย่อ 112 (retrace < 100%)
            + _leg(112, w3_top, 30))        # W3 → ยอดใหม่


def _bull_1234(w4=140.0, tail=None):
    """ซีรีส์ขาขึ้นที่นับได้ 1-2-3-4 (W4 = 140 > ยอด W1 130 → ผ่าน R4)

    ⚠️ ท้ายซีรีส์ต้อง "เด้งขึ้น" ไม่ใช่นิ่ง — pivot คลื่น 4 จะ lock ได้ต้องมี excursion
    ฝั่งตรงข้าม >= threshold · ราคานิ่ง = ไม่มีวัน lock = real-time มองไม่เห็น (ถูกแล้ว)
    และเด้งแบบขึ้นถึงแท่งสุดท้าย = ไม่เกิด fractal high ใหม่ (ต้องมี W แท่งขวา)"""
    seq = _base_123() + _leg(175, w4, 22)                 # W4
    seq += tail if tail is not None else _leg(w4, w4 * 1.09, 25)
    return _mk(seq)


def self_test():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + name)
        ok = ok and bool(cond)

    print("[self-test] screener.elliott")

    c = _bull_1234()
    r = current_partial(c)
    check("ขาขึ้นนับได้ 1-2-3-4 → code=4u", r is not None and r["code"] == "4u")
    check("stage=4 · direction=bull", r is not None and r["stage"] == 4 and r["direction"] == "bull")

    # กลับด้านทุกราคา → ต้องได้ขาลง (นิยามสมมาตร)
    inv = [{"open": 300 - x["open"], "high": 300 - x["low"], "low": 300 - x["high"],
            "close": 300 - x["close"], "volume": x["volume"]} for x in c]
    ri = current_partial(inv)
    check("กลับด้านราคา → 4d (สมมาตร)", ri is not None and ri["code"] == "4d")

    # W4 ย่อลึกจนหลุดยอด W1 (130) → R4 พัง = ไม่ใช่ 1-2-3-4 อีกต่อไป
    r_bad4 = current_partial(_bull_1234(w4=120.0))
    check("W4 หลุดยอดคลื่น 1 → ไม่ใช่ขั้น 4", r_bad4 is None or r_bad4["stage"] != 4)

    # ยังไม่มี W4 (ย่อจากยอด W3 แต่ยังไม่ลึก) → ต้องได้ 1-2-3
    r3 = current_partial(_mk(_base_123() + _leg(175, 160, 25)))
    check("จบที่คลื่น 3 (ย่อตื้น) → 3u", r3 is not None and r3["code"] == "3u")

    # 🔴 เคสสำคัญ: รูปทรงยังผ่าน R1/R2 แต่ราคาไหลหลุดยอดคลื่น 1 ไปแล้ว = การนับตาย
    #    (ขาลงยาวถึงแท่งสุดท้าย → ยังไม่เกิด pivot ใหม่มาล้างการนับ → ต้องพึ่ง _still_alive)
    dead = _mk(_base_123() + _leg(175, 125, 30))
    cfgd, atsd = cfg_for("1d"), None
    atsd = compute_atr_series(dead)
    pv_dead = find_pivots(dead, cfgd, atsd)
    check("เคสตาย: รูปทรง 1-2-3 ยังผ่านกติกา (ถ้าไม่มีด่านนี้จะขึ้นป้าย)",
          len(pv_dead) >= 4 and _check_123(pv_dead[-4:]) == 1)
    check("เคสตาย: ราคาหลุดยอดคลื่น 1 → ไม่ขึ้นป้าย", current_partial(dead) is None)

    # ด่าน _still_alive ตรงๆ
    ac = _mk([100.0] * 5 + [95.0] * 5)
    check("_still_alive: หลุดเส้นคลื่น 1 → False", _still_alive(ac, 4, 99.0, 1) is False)
    check("_still_alive: ยังไม่หลุด → True", _still_alive(ac, 4, 90.0, 1) is True)

    # ด่านความสด — pivot ที่ lock นานแล้ว = ค้างเก่า ไม่ใช่สถานะปัจจุบัน
    check("บีบ max_age_bars=1 → None (ด่านอายุทำงาน)",
          current_partial(c, max_age_bars=1) is None)
    check("อายุที่วัดได้ต้องอยู่ในกรอบ default", r is not None and 0 <= r["age_bars"] <= MAX_AGE_BARS)

    # กันขึ้นป้ายจากความว่างเปล่า
    check("แท่งน้อยเกิน → None", current_partial(_mk([100.0] * 10)) is None)
    check("ราคานิ่งสนิท (ไม่มี pivot) → None", current_partial(_mk([100.0] * 300)) is None)

    # deterministic — รันซ้ำต้องได้เท่าเดิม
    check("deterministic (รันซ้ำผลเท่าเดิม)",
          current_partial(_bull_1234()) == current_partial(_bull_1234()))

    # wave_code = ทางลัดของ current_partial
    check("wave_code() ตรงกับ current_partial()['code']", wave_code(c) == r["code"])

    # กติกาโครงสร้างระดับ pivot (ตรวจตรงๆ ไม่ผ่าน series)
    P = [{"index": i, "price": p, "type": t} for i, (p, t) in enumerate(
        [(100, "L"), (130, "H"), (112, "L"), (175, "H"), (150, "L")])]
    check("_check_1234 ขาขึ้นถูกต้อง → sgn=1", _check_1234(P) == 1)
    P[4]["price"] = 125          # W4 หลุดยอด W1 (130)
    check("_check_1234 R4 พัง → None", _check_1234(P) is None)
    P[4]["price"] = 150
    P[2]["price"] = 98           # W2 retrace เกิน 100% ของ W1
    check("_check_1234 R1 พัง → None", _check_1234(P) is None)
    P[2]["price"] = 112
    P[3]["price"] = 128          # W3 ไม่ทำ new extreme
    check("_check_1234 R2 พัง → None", _check_1234(P) is None)
    check("_check_123 R2 พัง → None", _check_123(P[:4]) is None)

    print("[self-test] " + ("ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    print(__doc__)
