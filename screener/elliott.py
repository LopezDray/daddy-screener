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

════════════════════════════════════════════════════════════════════════════════
🔁 SOURCE OF TRUTH = `DaddyInvestor/chart-elliott.js` (เครื่องยนต์ที่แผงในแอปใช้จริง)
   ไฟล์นี้เป็น **port ตรง** ของมัน — `detect_state()` = `detectWaves()` เฉพาะส่วนที่กระทบ
   state (ตัด fib/correction/clarity/post5/projectWave5 ซึ่งเป็น render-only)

   ทำไมต้องเป๊ะ: user เห็นผลของ Elliott 2 ที่บนเว็บเดียวกัน (ป้าย 🌊 ในตาราง Universe
   กับแผงในหน้าเจาะลึก) — ถ้าสองที่ไม่ตรงกัน = ป้ายโกหก · **บั๊กจริง 2026-08-01:**
   QCRH ติดป้าย "ถึงคลื่น 4" ขณะที่แผงบอก "นับครบ 5 คลื่น" เพราะเวอร์ชันแรกของไฟล์นี้
   พอร์ตมาแค่ชั้น primitive (ATR/pivots/lock) แล้ว**เขียนชั้นตัดสินใจขึ้นเองใหม่** จึงขาด
   ด่านสำคัญของ detectWaves ไปหมด (ไม่รู้จัก impulse ครบ 5 · ไม่มีตัวกรองขนาด · อายุคนละฐาน)

   ⚖️ กติกาต่อจากนี้: อยากให้เข้มขึ้น → **แก้ chart-elliott.js ก่อน** แล้วให้ไฟล์นี้ตาม
      ห้าม diverge เงียบๆ ฝั่งเดียว · gate ที่บังคับ = tests/test_parity_vs_chart.py
      (รัน engine ทั้งสองบน candle ชุดเดียวกัน state ต้องตรง 100%)
════════════════════════════════════════════════════════════════════════════════

หลักกัน look-ahead/repaint (เหมือนต้นทางเป๊ะ):
  - threshold ZigZag ใช้ ATR **ณ เวลาของ pivot** ไม่ใช่ ATR ตัวเดียวจาก series เต็ม
    (ATR ตัวเดียวทำให้เกณฑ์ถูกแก้ย้อนหลัง → โครงสร้างที่เคยเจอหายไป)
  - ทุก pivot ที่นับต้อง lock ได้จริง (lock_index) = แท่งแรกที่ ZigZag real-time จะ commit

stdlib ล้วน · ไม่แตะ network · CPU อย่างเดียว (Yahoo 0 call เพิ่ม — reuse candles ของ scan)
self-test: python -m screener.elliott --self-test     # $0
"""

from screener.patterns import PATTERN_CFG, TF_ALIAS

ATR_MULT = 1.5                 # = ATR_MULT ใน chart-elliott.js

# mirror EW_CFG ของ chart-elliott.js แบบตรงตัว — **อย่า derive จาก PATTERN_CFG**
# เหตุ: minBars ของ Elliott (120) ต่างจาก PATTERN_CFG["1d"]["minBars"] (80) และการผูกกับ
# PATTERN_CFG ทำให้ engine เลื่อนตามคนอื่นโดยไม่ตั้งใจ · self_test มีด่านเช็คว่า W/minPct
# ยังตรงกับ PATTERN_CFG อยู่ (จับ drift ฝั่ง screener) ส่วน parity test จับ drift ฝั่ง JS
EW_CFG = {
    "1d":  {"W": 5, "minPct": 0.03, "minBars": 120},
    "1wk": {"W": 3, "minPct": 0.05, "minBars": 80},
    "1mo": {"W": 2, "minPct": 0.08, "minBars": 40},
}

# default ที่แผงใช้จริง — elliott-panel.js:158 เรียก detectWaves(bars,"1d") ไม่ส่ง opts
MAX_AGE_BARS = 380             # นับจาก **index ของ pivot** ไม่ใช่ index ที่ lock
MIN_SPAN_SHARE = 0.20          # คลื่นต้องกินพื้นที่ >= 20% ของกรอบราคาในหน้าต่างที่ดู

# หน้าต่างข้อมูลที่ป้อน engine — แผงดึง /daily-candles?range=2y (elliott-panel.js:104)
# แต่ scan ดึง Yahoo range=5y → ต้อง slice ให้เท่ากันก่อนคำนวณ ไม่ใช่แค่ปรับ max_age:
# เส้นทาง ZigZag ขึ้นกับ "จุดเริ่มหน้าต่าง" (pivot ตัวแรกกำหนดตัวถัดไปทั้งสาย) และ
# viewRange (hi-lo) ที่ใช้ตัดสิน MIN_SPAN_SHARE ก็เปลี่ยนตามหน้าต่างด้วย
EW_WINDOW_BARS = 504           # ≈ 2 ปีเทรด


def cfg_for(tf):
    return EW_CFG[TF_ALIAS.get(tf, "1d")]


def compute_atr_series(candles, period=14):
    """ATR แบบ "ณ เวลานั้น" — out[i] = ATR จากแท่ง 0..i เท่านั้น
    ต้องตรงกับ chart-elliott.js::computeATRSeries เป๊ะ"""
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
    """Fractal pivots + ZigZag — mirror chart-elliott.js::findPivots
    threshold ใช้ ATR ณ เวลาของ pivot (ดู compute_atr_series)"""
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


def find_impulses(pivots, include_truncated=False):
    """impulse 5 คลื่นสมบูรณ์ตามกติกาแข็ง R1-R5 — mirror chart-elliott.js::findImpulses
    ขาขึ้น: L0,H1,L2,H3,L4,H5 · ขาลง: กลับเครื่องหมาย"""
    out = []
    for i in range(len(pivots) - 5):
        six = pivots[i:i + 6]
        types = "".join(p["type"] for p in six)
        if types == "LHLHLH":
            direction, sgn = "bull", 1
        elif types == "HLHLHL":
            direction, sgn = "bear", -1
        else:
            continue
        p0, p1, p2, p3, p4, p5 = (p["price"] for p in six)
        w1 = sgn * (p1 - p0)
        w3 = sgn * (p3 - p2)
        w5 = sgn * (p5 - p4)
        if w1 <= 0 or w3 <= 0 or w5 <= 0:
            continue
        r1 = sgn * (p2 - p0) > 0                 # R1: W2 retrace < 100% ของ W1
        r2 = sgn * (p3 - p1) > 0                 # R2: W3 ทำ new extreme
        r3 = w3 > min(w1, w5) - 1e-12            # R3: W3 ไม่สั้นสุด
        r4 = sgn * (p4 - p1) > 0                 # R4: W4 ไม่เข้าเขต W1 (strict)
        r5 = sgn * (p5 - p3) > 0                 # R5: W5 new extreme
        if not (r1 and r2 and r3 and r4):
            continue
        truncated = not r5
        if truncated and not include_truncated:
            continue
        out.append({
            "direction": direction,
            "pivots": six,
            "span": sgn * (p5 - p0),
            "sgn": sgn,
            "truncated": truncated,
        })
    return out


def find_partial_1234(pivots):
    """ทุกช่วง 5 pivot ที่นับเป็น 1-2-3-4 ได้ — mirror chart-elliott.js::findPartial1234
    ⚠️ สแกน **ทุก** window (ไม่ใช่แค่หาง) — คนเรียกค่อยกรองว่าต้องจบที่ pivot ล่าสุด
       เหมือน JS · R3 ตรวจไม่ได้เพราะคลื่น 5 ยังไม่เกิด"""
    out = []
    for i in range(len(pivots) - 4):
        five = pivots[i:i + 5]
        types = "".join(p["type"] for p in five)
        if types == "LHLHL":
            direction, sgn = "bull", 1
        elif types == "HLHLH":
            direction, sgn = "bear", -1
        else:
            continue
        p0, p1, p2, p3, p4 = (p["price"] for p in five)
        w1 = sgn * (p1 - p0)
        w3 = sgn * (p3 - p2)
        if w1 <= 0 or w3 <= 0:
            continue
        if not (sgn * (p2 - p0) > 0):      # R1
            continue
        if not (sgn * (p3 - p1) > 0):      # R2
            continue
        if not (sgn * (p4 - p1) > 0):      # R4
            continue
        out.append({"direction": direction, "pivots": five, "sgn": sgn})
    return out


def find_partial_123(pivots):
    """ทุกช่วง 4 pivot ที่นับเป็น 1-2-3 ได้ — mirror chart-elliott.js::findPartial123"""
    out = []
    for i in range(len(pivots) - 3):
        four = pivots[i:i + 4]
        types = "".join(p["type"] for p in four)
        if types == "LHLH":
            direction, sgn = "bull", 1
        elif types == "HLHL":
            direction, sgn = "bear", -1
        else:
            continue
        p0, p1, p2, p3 = (p["price"] for p in four)
        w1 = sgn * (p1 - p0)
        w3 = sgn * (p3 - p2)
        if w1 <= 0 or w3 <= 0:
            continue
        if not (sgn * (p2 - p0) > 0):      # R1
            continue
        if not (sgn * (p3 - p1) > 0):      # R2
            continue
        out.append({"direction": direction, "pivots": four, "sgn": sgn})
    return out


def detect_state(candles, tf="1d", max_age_bars=MAX_AGE_BARS,
                 min_span_share=MIN_SPAN_SHARE):
    """สถานะการนับคลื่น ณ แท่งสุดท้าย — **port ตรงของ chart-elliott.js::detectWaves**

    คืน {"state", "direction", "code"} หรือ None
      state: "complete" (ครบ 5 คลื่น) · "forming" (นับได้ถึง 4) ·
             "early" (นับได้ถึง 3) · "invalid" (การนับพังแล้ว)
      code:  "4u"/"4d" เมื่อ forming · "3u"/"3d" เมื่อ early · None ที่เหลือ

    ลำดับการตัดสิน (ห้ามสลับ — นี่คือหัวใจที่เวอร์ชันแรกทำหาย):
      1. หา impulse ครบ 5 ที่ผ่านด่าน lock/อายุ/ขนาด → เลือกตัวที่ **จบล่าสุด** = best
      2. หา 1-2-3-4 ที่จบ**ที่ pivot ตัวสุดท้าย** → ใช้ก็ต่อเมื่อ **ใหม่กว่า best**
         (ผู้ใช้ถามว่า "ตอนนี้อยู่ตรงไหน" ไม่ใช่ "เคยอยู่ตรงไหน")
      3. ถ้าไม่เข้าข้อ 2 → ลอง 1-2-3 ด้วยเงื่อนไขเดียวกัน + ราคายังไม่หลุดยอดคลื่น 1
      4. ไม่มีอะไรกำลังเดิน แต่มี best → "complete"
    """
    cfg = cfg_for(tf)
    if not isinstance(candles, list) or len(candles) < cfg["minBars"]:
        return None
    ats = compute_atr_series(candles)
    if not any(v is not None for v in ats):
        return None

    pivots = find_pivots(candles, cfg, ats)
    n = len(candles)

    # กรอบราคาที่ผู้ใช้เห็นอยู่ — ใช้ตัดสินว่าคลื่น "ใหญ่พอจะเป็นเรื่อง" ไหม
    lo = min(c["low"] for c in candles)
    hi = max(c["high"] for c in candles)
    view_range = hi - lo

    def big_enough(a_price, b_price):
        return view_range <= 0 or abs(a_price - b_price) / view_range >= min_span_share

    # ── 1. impulse ครบ 5 ที่ยืนยันแล้ว → เลือกตัวจบล่าสุด ──
    best = None
    for imp in find_impulses(pivots):
        if lock_index(candles, imp["pivots"][5], cfg, ats) is None:
            continue                                          # ยังไม่ยืนยัน
        if n - imp["pivots"][5]["index"] > max_age_bars:
            continue                                          # เก่าเกินกว่าจะเกี่ยว
        if view_range > 0 and abs(imp["span"]) / view_range < min_span_share:
            continue                                          # จิ๋วเกินไป
        if best is None or imp["pivots"][5]["index"] > best["pivots"][5]["index"]:
            best = imp

    last_pivot = pivots[-1] if pivots else None
    last_close = candles[n - 1]["close"]

    # ── 2. การนับที่ "ยังเดินอยู่" (1-2-3-4 · คลื่น 4 เป็น pivot ล่าสุด) ──
    live = [pa for pa in find_partial_1234(pivots)
            if last_pivot is not None
            and pa["pivots"][4]["index"] == last_pivot["index"]
            and lock_index(candles, pa["pivots"][4], cfg, ats) is not None
            and n - pa["pivots"][4]["index"] <= max_age_bars
            and big_enough(pa["pivots"][4]["price"], pa["pivots"][0]["price"])]

    use_live = bool(live) and (
        best is None or live[-1]["pivots"][4]["index"] > best["pivots"][5]["index"])

    if use_live:
        pa = live[-1]
        w4price = pa["pivots"][4]["price"]
        # ราคาหลุดคลื่น 4 ไปแล้ว = การนับนี้ใช้ไม่ได้ (กติกา R4 พัง)
        invalid = pa["sgn"] * (last_close - w4price) < 0
        return {
            "state": "invalid" if invalid else "forming",
            "direction": pa["direction"],
            "code": None if invalid else ("4u" if pa["sgn"] > 0 else "4d"),
        }

    # ── 3. ขั้นต้นกว่า: นับได้ถึงคลื่น 3 (คลื่น 3 เป็น pivot ล่าสุด) ──
    #    โชว์เฉพาะที่ยังไม่พัง (ราคายังไม่หลุดยอดคลื่น 1) — 1-2-3 ที่พังมีเป็นหมื่นเคส
    early = [pa for pa in find_partial_123(pivots)
             if last_pivot is not None
             and pa["pivots"][3]["index"] == last_pivot["index"]
             and lock_index(candles, pa["pivots"][3], cfg, ats) is not None
             and n - pa["pivots"][3]["index"] <= max_age_bars
             and pa["sgn"] * (last_close - pa["pivots"][1]["price"]) > 0
             and big_enough(pa["pivots"][3]["price"], pa["pivots"][0]["price"])
             and (best is None or pa["pivots"][3]["index"] > best["pivots"][5]["index"])]
    if early:
        pa = early[-1]
        return {
            "state": "early",
            "direction": pa["direction"],
            "code": "3u" if pa["sgn"] > 0 else "3d",
        }

    if best is None:
        return None

    return {"state": "complete", "direction": best["direction"], "code": None}


def wave_code(candles, tf="1d"):
    """ค่าที่ลงคอลัมน์ `ew` ของ us-all-table.json — "3u"/"4u"/"3d"/"4d" หรือ None

    None เมื่อ: นับครบ 5 คลื่นแล้ว (complete) · การนับพัง (invalid) · ไม่มีโครงสร้าง
    → คอลัมน์นี้ตอบเฉพาะ "กำลังเดินคลื่นอยู่" เท่านั้น ตรงกับป้ายบนแผงคำต่อคำ
    """
    if not candles:
        return None
    res = detect_state(candles[-EW_WINDOW_BARS:], tf)     # หน้าต่างเดียวกับแผง
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


def _pad(seq, bars):
    """เติมหัวซีรีส์ให้ยาวพอ minBars โดยไม่สร้าง pivot ใหม่ — ไต่ขึ้นช้าๆ เข้าหาจุดเริ่ม
    (ขาขึ้นต่อเนื่องไม่เกิด fractal low และจบด้วยการลงของ _base_123 พอดี)"""
    return _leg(seq[0] * 0.97, seq[0], bars) + seq


def _bull_1234(w4=140.0, tail=None):
    """ซีรีส์ขาขึ้นที่นับได้ 1-2-3-4 (W4 = 140 > ยอด W1 130 → ผ่าน R4)

    ⚠️ ท้ายซีรีส์ต้อง "เด้งขึ้น" ไม่ใช่นิ่ง — pivot คลื่น 4 จะ lock ได้ต้องมี excursion
    ฝั่งตรงข้าม >= threshold · ราคานิ่ง = ไม่มีวัน lock = real-time มองไม่เห็น (ถูกแล้ว)
    และเด้งแบบขึ้นถึงแท่งสุดท้าย = ไม่เกิด fractal high ใหม่ (ต้องมี W แท่งขวา)"""
    seq = _base_123() + _leg(175, w4, 22)                 # W4
    seq += tail if tail is not None else _leg(w4, w4 * 1.09, 25)
    return _mk(_pad(seq, 40))


def _bull_12345(tail=None):
    """ขาขึ้นที่ **นับครบ 5 คลื่น** แล้ว: 100→130→112→175→140→200 (R1-R5 ผ่านหมด)
    หางลงมาทำให้ยอดคลื่น 5 lock ได้ และไม่สร้างการนับใหม่ที่ใหม่กว่า
    = เคสเดียวกับ QCRH ที่แผงบอก "นับครบ 5 คลื่น" → ป้ายต้องเงียบ"""
    seq = _base_123() + _leg(175, 140, 22) + _leg(140, 200, 28)
    seq += tail if tail is not None else _leg(200, 168, 30)
    return _mk(_pad(seq, 40))


def _bull_12345_then_1234():
    """ครบ 5 คลื่นแล้ว **ตามด้วย** 1-2-3-4 ชุดใหม่ที่ใหม่กว่า → ต้องโชว์ชุดใหม่ (4u)
    150(L0') → 190(W1') → 165(W2') → 230(W3') → 200(W4' > 190 ผ่าน R4) → เด้ง"""
    seq = (_base_123() + _leg(175, 140, 22) + _leg(140, 200, 28)   # ครบ 5 คลื่น
           + _leg(200, 150, 25) + _leg(150, 190, 22) + _leg(190, 165, 18)
           + _leg(165, 230, 26) + _leg(230, 200, 20) + _leg(200, 222, 25))
    return _mk(_pad(seq, 40))


def self_test():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + name)
        ok = ok and bool(cond)

    def state_of(c, **kw):
        r = detect_state(c, **kw)
        return r["state"] if r else None

    print("[self-test] screener.elliott")

    # ── config ไม่หลุดจาก PATTERN_CFG (จับ drift ฝั่ง screener) ──
    check("EW_CFG W/minPct ยังตรงกับ PATTERN_CFG ทุก TF",
          all(EW_CFG[k]["W"] == PATTERN_CFG[k]["W"]
              and abs(EW_CFG[k]["minPct"] - PATTERN_CFG[k]["minPct"]) < 1e-12
              for k in EW_CFG))

    # ── forming (นับได้ถึงคลื่น 4) ──
    c = _bull_1234()
    r = detect_state(c)
    check("ขาขึ้นนับได้ 1-2-3-4 → forming/4u",
          r is not None and r["state"] == "forming" and r["code"] == "4u")
    check("direction = bull", r is not None and r["direction"] == "bull")

    inv = [{"open": 300 - x["open"], "high": 300 - x["low"], "low": 300 - x["high"],
            "close": 300 - x["close"], "volume": x["volume"]} for x in c]
    ri = detect_state(inv)
    check("กลับด้านราคา → 4d (สมมาตร)", ri is not None and ri["code"] == "4d")

    r_bad4 = detect_state(_bull_1234(w4=120.0))
    check("W4 หลุดยอดคลื่น 1 → ไม่ใช่ forming",
          r_bad4 is None or r_bad4["state"] != "forming")

    # ── early (นับได้ถึงคลื่น 3) ──
    r3 = detect_state(_mk(_pad(_base_123() + _leg(175, 160, 25), 40)))
    check("จบที่คลื่น 3 (ย่อตื้น) → early/3u",
          r3 is not None and r3["state"] == "early" and r3["code"] == "3u")

    # ราคาไหลหลุดยอดคลื่น 1 → early ถูกกรองทิ้ง (ไม่ขึ้นป้าย)
    dead = _mk(_pad(_base_123() + _leg(175, 125, 30), 40))
    check("ราคาหลุดยอดคลื่น 1 → ไม่ขึ้นป้าย", wave_code(dead) is None)

    # ── 🔴 หัวใจของบั๊ก QCRH: ครบ 5 คลื่นแล้วต้องเงียบ ──
    done5 = _bull_12345()
    check("นับครบ 5 คลื่น → state=complete", state_of(done5) == "complete")
    check("นับครบ 5 คลื่น → ป้ายเงียบ (เคส QCRH)", wave_code(done5) is None)
    check("เคสครบ 5: engine เห็น impulse จริง (ไม่ใช่ None เพราะหาไม่เจอ)",
          len(find_impulses(find_pivots(
              done5, cfg_for("1d"), compute_atr_series(done5)))) >= 1)

    # ครบ 5 แล้วมีชุดใหม่ที่ใหม่กว่า → ต้องโชว์ชุดใหม่
    newer = _bull_12345_then_1234()
    check("ครบ 5 แล้วมี 1-2-3-4 ใหม่กว่า → forming/4u", wave_code(newer) == "4u")

    # ── ตัวกรองขนาด (minSpanShare) ──
    check("บีบ min_span_share=0.9 → คลื่นเล็กเกิน ไม่ขึ้นป้าย",
          detect_state(c, min_span_share=0.9) is None)
    check("ปลด min_span_share=0 → กลับมา forming",
          state_of(c, min_span_share=0.0) == "forming")

    # ── ด่านอายุ (นับจาก index ของ pivot) ──
    check("บีบ max_age_bars=1 → None (ด่านอายุทำงาน)",
          detect_state(c, max_age_bars=1) is None)

    # ── invalid: ราคาปิดล่าสุดหลุดคลื่น 4 ──
    #    เด้งขึ้นให้ pivot คลื่น 4 lock ก่อน แล้วรูดลงใน < W แท่ง (ไม่ทันเกิด pivot ใหม่)
    inv4 = _bull_1234(tail=_leg(140, 158, 22) + _leg(158, 133, 4))
    ri4 = detect_state(inv4)
    check("ปิดล่าสุดหลุดคลื่น 4 → state=invalid", ri4 is not None and ri4["state"] == "invalid")
    check("invalid → ป้ายเงียบ", wave_code(inv4) is None)

    # ── กันขึ้นป้ายจากความว่างเปล่า ──
    check("แท่งน้อยกว่า minBars → None", detect_state(_mk([100.0] * 100)) is None)
    check("ราคานิ่งสนิท (ไม่มี pivot) → None", detect_state(_mk([100.0] * 300)) is None)
    check("candles ว่าง → None (ไม่ throw)", wave_code([]) is None)

    # ── deterministic ──
    check("deterministic (รันซ้ำผลเท่าเดิม)",
          detect_state(_bull_1234()) == detect_state(_bull_1234()))

    # ── wave_code = ทางลัด + slice หน้าต่าง ──
    check("wave_code() ตรงกับ detect_state()['code']", wave_code(c) == r["code"])
    # ต่อประวัติเก่า 700 แท่งไว้ข้างหน้าแบบ **ราคาต่อเนื่อง** (ไหลลง 400 → จุดเริ่มของ c)
    # ถ้าไม่ slice: viewRange จะกินตั้งแต่ 400 → คลื่นกลายเป็น 13% ของกรอบ → ถูกกรองทิ้ง
    # slice 504 แท่งแล้ว: กรอบแคบลงเหลือ ~245 → คลื่นกลับมา 27% → ยังเป็น 4u เหมือนแผง
    long_hist = _mk(_leg(400, c[0]["open"], 700)) + c
    check("wave_code slice หน้าต่าง 2 ปี (ของเก่ากว่านั้นไม่กวน)",
          wave_code(long_hist) == "4u")
    check("ถ้าไม่ slice จะถูกตัวกรองขนาดกินทิ้ง (พิสูจน์ว่า slice จำเป็นจริง)",
          detect_state(long_hist) is None)

    # ── กติกาโครงสร้างระดับ pivot (ตรวจตรงๆ ไม่ผ่าน series) ──
    P = [{"index": i * 12, "price": p, "type": t} for i, (p, t) in enumerate(
        [(100, "L"), (130, "H"), (112, "L"), (175, "H"), (150, "L")])]
    check("find_partial_1234 ขาขึ้นถูกกติกา → รับ", len(find_partial_1234(P)) == 1)
    P[4]["price"] = 125          # W4 กินเขตคลื่น 1 (130)
    check("find_partial_1234 R4 พัง → ไม่รับ", len(find_partial_1234(P)) == 0)
    P[4]["price"] = 150
    P[2]["price"] = 98           # W2 retrace เกิน 100% ของ W1
    check("find_partial_1234 R1 พัง → ไม่รับ", len(find_partial_1234(P)) == 0)
    P[2]["price"] = 112
    P[3]["price"] = 128          # W3 ไม่ทำ new extreme
    check("find_partial_1234 R2 พัง → ไม่รับ", len(find_partial_1234(P)) == 0)
    check("find_partial_123 R2 พัง → ไม่รับ", len(find_partial_123(P[:4])) == 0)

    # find_impulses — R3 (W3 ห้ามสั้นสุด) และ R5
    Q = [{"index": i * 12, "price": p, "type": t} for i, (p, t) in enumerate(
        [(100, "L"), (130, "H"), (112, "L"), (175, "H"), (150, "L"), (210, "H")])]
    check("find_impulses ครบกติกา → รับ", len(find_impulses(Q)) == 1)
    Q[3]["price"] = 133          # W3 = 21 สั้นกว่าทั้ง W1(30) และ W5
    check("find_impulses R3 พัง (W3 สั้นสุด) → ไม่รับ", len(find_impulses(Q)) == 0)
    Q[3]["price"] = 175
    Q[5]["price"] = 170          # W5 ไม่ทำ new extreme → truncated
    check("find_impulses R5 พัง → drop (truncated)", len(find_impulses(Q)) == 0)
    check("find_impulses include_truncated=True → รับ",
          len(find_impulses(Q, include_truncated=True)) == 1)

    print("[self-test] " + ("ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    print(__doc__)
