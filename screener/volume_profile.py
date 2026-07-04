#!/usr/bin/env python3
"""
Volume Profile — port ตรงจาก DaddyInvestor app.js computeVolumeProfile()
+ เพิ่ม Value Area (VAL/VAH) และ overhead supply

หลักการ (ต้องตรงกับ app.js เพื่อให้ chart ฝั่งเว็บกับ screener คิดเหมือนกัน):
  แบ่งราคาเป็น n_bins แล้วแจก volume ของแต่ละแท่งเข้า bin ตามสัดส่วน overlap
  ของช่วง [low, high] → อนุรักษ์ volume รวม (ไม่โยนทั้งก้อนลง bin เดียว)
"""


def compute_volume_profile(candles, n_bins=40, close=None):
    """
    candles: list of {high, low, volume}
    close:   ราคาปัจจุบัน (สำหรับคำนวณ overhead supply) — ถ้า None ใช้ close แท่งสุดท้าย
    คืน dict {poc, val, vah, overhead_supply_pct, lo, hi, bins} หรือ None
    """
    valid = [c for c in candles
             if _finite(c.get("high")) and _finite(c.get("low"))
             and _finite(c.get("volume")) and c["volume"] > 0 and c["high"] >= c["low"]]
    if len(valid) < 10:
        return None

    lo = min(c["low"] for c in valid)
    hi = max(c["high"] for c in valid)
    if not (hi > lo):
        return None

    step = (hi - lo) / n_bins
    bins = [{"p0": lo + i * step, "p1": lo + (i + 1) * step, "vol": 0.0}
            for i in range(n_bins)]

    def bin_idx(p):
        return min(n_bins - 1, max(0, int((p - lo) / step)))

    for c in valid:
        rng = c["high"] - c["low"]
        if rng < step * 1e-6:
            bins[bin_idx((c["high"] + c["low"]) / 2)]["vol"] += c["volume"]
            continue
        for i in range(bin_idx(c["low"]), bin_idx(c["high"]) + 1):
            ovl = min(c["high"], bins[i]["p1"]) - max(c["low"], bins[i]["p0"])
            if ovl > 0:
                bins[i]["vol"] += c["volume"] * (ovl / rng)

    total = sum(b["vol"] for b in bins)
    if not (total > 0):
        return None

    poc_index = max(range(n_bins), key=lambda i: bins[i]["vol"])
    poc = (bins[poc_index]["p0"] + bins[poc_index]["p1"]) / 2

    val_i, vah_i = _value_area(bins, poc_index, total, frac=0.70)
    val = bins[val_i]["p0"]
    vah = bins[vah_i]["p1"]

    if close is None:
        close = valid[-1].get("close", poc)
    overhead = sum(b["vol"] for b in bins if b["p0"] > close)
    overhead_pct = round(overhead / total * 100, 1)

    return {
        "poc": round(poc, 4),
        "val": round(val, 4),
        "vah": round(vah, 4),
        "overhead_supply_pct": overhead_pct,
        "lo": round(lo, 4),
        "hi": round(hi, 4),
        "bins": bins,
    }


def _value_area(bins, poc_index, total, frac=0.70):
    """ขยายจาก POC ออกทั้ง 2 ฝั่ง หยิบ bin ที่ volume มากกว่าเข้ามาก่อน จนถึง frac ของ total"""
    n = len(bins)
    lo = hi = poc_index
    acc = bins[poc_index]["vol"]
    target = total * frac
    while acc < target:
        up_i = hi + 1
        dn_i = lo - 1
        up_v = bins[up_i]["vol"] if up_i < n else None
        dn_v = bins[dn_i]["vol"] if dn_i >= 0 else None
        if up_v is None and dn_v is None:
            break
        if dn_v is None or (up_v is not None and up_v >= dn_v):
            hi = up_i
            acc += up_v
        else:
            lo = dn_i
            acc += dn_v
    return lo, hi


def _finite(x):
    try:
        return x is not None and float(x) == float(x) and abs(float(x)) != float("inf")
    except (TypeError, ValueError):
        return False
