#!/usr/bin/env python3
"""
Yahoo Finance candle fetcher — port จาก DaddyInvestor scan_nasdaq_screener.py
+ เพิ่มการเก็บ VOLUME (ของเดิมไม่ได้เก็บ) เพื่อคำนวณ Volume Profile

ฟรี ไม่ใช้ key · retry/backoff + host fallback (query1/query2)
รันบน GitHub Actions runner (IP ของ Azure/GitHub — แยกจาก production)
"""

import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone, date as dateobj

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; daddy-screener/1.0)"}
_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]

MIN_CANDLES = {"1d": 160, "1wk": 35, "1mo": 12}

# ── congestion tracking (adaptive throttle ตอนสแกน universe ใหญ่ ~7k) ──────────
# นับ 429 ต่อเนื่อง — run_scan อ่านผ่าน congestion_penalty() เพื่อถ่วง sleep เพิ่ม
# เมื่อ Yahoo เริ่มบ่น (ไม่แตะ candle data → parity ของ 4 universe เดิมไม่เปลี่ยน)
_consecutive_429 = 0


def congestion_penalty():
    """วินาทีถ่วงเพิ่มต่อ request ตามจำนวน 429 ต่อเนื่องล่าสุด: >20=+0.6s · >10=+0.3s · else 0"""
    if _consecutive_429 > 20:
        return 0.6
    if _consecutive_429 > 10:
        return 0.3
    return 0.0


def _retry_after(e, fallback):
    """อ่าน header Retry-After (วินาที) ถ้า Yahoo ส่งมา — ไม่งั้นใช้ fallback backoff"""
    try:
        ra = e.headers.get("Retry-After") if e.headers else None
        if ra and ra.isdigit():
            return min(float(ra), 30.0)   # cap 30s กัน header เพี้ยนค้างนาน
    except Exception:  # noqa: BLE001
        pass
    return fallback


def fetch_daily(symbol, rng="5y", retries=3):
    """ดึงแท่งเทียนรายวัน (พร้อม volume) จาก Yahoo v8 chart — คืน list เรียงตามเวลา"""
    global _consecutive_429
    encoded = urllib.parse.quote(symbol)
    last_err = None
    for attempt in range(retries):
        for host in _HOSTS:
            url = f"https://{host}/v8/finance/chart/{encoded}?interval=1d&range={rng}"
            try:
                req = urllib.request.Request(url, headers=_YAHOO_HEADERS)
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read())
                result = data.get("chart", {}).get("result", [None])[0]
                if not result:
                    continue
                candles = _parse_result(result)
                if candles:
                    _consecutive_429 = 0            # สำเร็จ → reset congestion
                    return candles
            except urllib.error.HTTPError as e:
                last_err = f"{host} HTTP {e.code}"
                if e.code == 429:  # rate limited → honor Retry-After แล้วลอง host อื่น
                    _consecutive_429 += 1
                    time.sleep(_retry_after(e, 1.5 * (attempt + 1)))
            except Exception as e:  # noqa: BLE001
                last_err = f"{host} {e}"
                continue
        time.sleep(0.6 * (attempt + 1))
    if last_err:
        print(f"[yahoo] {symbol} failed: {last_err}", flush=True)
    return []


_DAY_S = 86400
# แท่ง 1wk/1mo ครอบหลายวัน → ราคาปิดล่าสุดเป็นวันไหนก็ได้ในช่วงแท่งนั้น
# ที่นี่ fetch_daily ดึง interval=1d อย่างเดียว (1wk/1mo ทำเองที่ resample) ⇒ ใช้แค่คีย์ "1d"
# แต่คงตารางเต็มไว้ให้ signature ตรง ③ — เคสร่วม close_repair_cases.json มีเคส weekly ด้วย
_REPAIR_SPAN_DAYS = {"1d": 0, "1wk": 6, "1mo": 31}


def yahoo_close_repair(result, max_span_days):
    """ซ่อมแท่งที่ Yahoo ส่ง close = null — port ที่ 3 (ALERT CONTRACT)

    ⚠️ **ห้ามคิดสูตรใหม่ / ห้ามสลับลำดับเงื่อนไข** — 3 ports ต้องตัดสินเหมือนกันทุกเคส:
      ② DaddyInvestor/scripts/daddy-asset-worker.js  `yahooCloseRepair`
      ③ DaddyInvestor/scripts/check_watchlist_alerts.py `yahoo_close_repair`  ← source of truth
      ④ ที่นี่
    เคสร่วม: DaddyInvestor/tests/fixtures/close_repair_cases.json
    ด่านข้าม repo: DaddyInvestor/tests/screener/test_close_repair_parity.py

    อาการจริง 2026-08-03 (owner แจ้ง "ราคาหุ้นค้าง 31 ก.ค."): Yahoo v8 chart คืนแท่งของวันที่
    **ปิดตลาดไปแล้ว** แบบ open/high/low/volume ครบ แต่ close + adjclose = null
    → ตัวกรอง `c is None` ใน _parse_result ดรอปแท่งทิ้ง = ทั้งกระดาน Universe ถอยไปใช้
    ข้อมูลของ session ก่อนหน้าเงียบ ๆ (= อาการ #7 "ล้าหลัง 1 วันเทรด")

    meta.regularMarketPrice ของ payload เดียวกันยังถูกต้อง → เติมกลับได้ · ซ่อมเฉพาะเมื่อครบ 4 ข้อ
    กันเดาราคาผิดลงตาราง:
      1. close หายจริง  2. high/low มาครบ  3. วันของ regularMarketTime อยู่ในช่วงแท่งนั้น
      4. ราคาอยู่ในช่วง low..high ของแท่งเอง
    Yahoo ซ่อมเมื่อไหร่ เงื่อนไข 1 ไม่เข้า → เงียบเอง (self-healing ไม่ต้องตามถอน)

    คืน callable(bar_date, low, high) -> float|None · หรือ None ถ้า meta ใช้ไม่ได้เลย
    """
    meta = (result or {}).get("meta") or {}
    try:
        price = float(meta.get("regularMarketPrice"))
        market_time = float(meta.get("regularMarketTime"))
    except (TypeError, ValueError):
        return None
    if not (price > 0):  # กัน NaN ด้วย (NaN > 0 เป็น False)
        return None

    try:
        offset = float(meta.get("gmtoffset") or 0)
    except (TypeError, ValueError):
        offset = 0.0
    # ปัดเป็น "วันตลาดท้องถิ่น" — // ของ Python floor เหมือน Math.floor ฝั่ง JS
    market_day = (int(market_time + offset) // _DAY_S) * _DAY_S

    def repair(bar_date, low, high):
        try:
            bar_day = int(datetime.strptime(bar_date, "%Y-%m-%d")
                          .replace(tzinfo=timezone.utc).timestamp())
        except (TypeError, ValueError):
            return None
        span = market_day - bar_day
        if span < 0 or span > max_span_days * _DAY_S:
            return None
        if low is None or high is None:
            return None
        try:
            lo, hi = float(low), float(high)
        except (TypeError, ValueError):
            return None
        if not (lo > 0) or hi < lo:
            return None
        if price < lo - 1e-6 or price > hi + 1e-6:
            return None
        return price

    return repair


def _parse_result(result):
    timestamps = result.get("timestamp", [])
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    opens = quote.get("open", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])
    # ALERT CONTRACT — ซ่อม close=null ก่อนดรอป (ดู yahoo_close_repair ข้างบน)
    # fetch_daily ดึง interval=1d อย่างเดียว ⇒ span = 0 (แท่งวันต้องเป็นวันเดียวกับ regularMarketTime)
    repair = yahoo_close_repair(result, _REPAIR_SPAN_DAYS["1d"])
    out = []
    for i, ts in enumerate(timestamps):
        try:
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            v = volumes[i] if i < len(volumes) else None
            # วันของแท่งเป็น UTC เหมือน ③ (time.gmtime) · strftime zero-pad เสมอ
            bar_date = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            if c is None and repair is not None and v is not None:
                # 🔴 เงื่อนไข `v is not None` เป็นของ port นี้โดยเฉพาะ — ③ ไม่มีเพราะมันไม่เก็บ volume เลย
                #    (check_watchlist_alerts.py :497-498 เก็บแค่ ts/open/high/low/close)
                #    ที่นี่ volume มีผลจริง: patterns.py:147 ใช้ตัดสิน volConfirmed → :229 เป็นคะแนน 10 แต้ม
                #    ถ้าปล่อยให้แท่งที่ volume=null ผ่านเข้ามา บรรทัดล่างจะแปลงเป็น 0.0
                #    ⇒ เบรกจริงถูกลดเกรดเงียบ ๆ (ก่อนแพตช์แท่งนี้ถูกดรอปทั้งแท่ง จึงไม่เคยมี volume=0 หลุดเข้ามา)
                #    อาการ glitch จริง 08-03 คือ o/h/l/volume **ครบ** ขาดแค่ close ⇒ เงื่อนไขนี้ไม่ตัดเคสที่ตั้งใจซ่อม
                c = repair(bar_date, l, h)
            if o is None or h is None or l is None or c is None:
                continue
            out.append({
                "time": bar_date,
                "open": float(o), "high": float(h), "low": float(l),
                "close": float(c),
                "volume": float(v) if v is not None else 0.0,
            })
        except (TypeError, ValueError, IndexError):
            continue
    return out


def resample(daily, interval):
    """resample รายวัน → รายสัปดาห์ (จันทร์) หรือรายเดือน — sum volume ต่อ bucket"""
    if interval == "1d":
        return daily
    buckets = {}
    order = []
    for c in daily:
        try:
            d = dateobj.fromisoformat(c["time"])
        except ValueError:
            continue
        if interval == "1wk":
            key = (d - timedelta(days=d.weekday())).isoformat()
        else:  # 1mo
            key = c["time"][:7] + "-01"
        if key not in buckets:
            buckets[key] = {"time": key, "open": c["open"], "high": c["high"],
                            "low": c["low"], "close": c["close"], "volume": c["volume"]}
            order.append(key)
        else:
            b = buckets[key]
            b["high"] = max(b["high"], c["high"])
            b["low"] = min(b["low"], c["low"])
            b["close"] = c["close"]          # last day of bucket
            b["volume"] += c["volume"]       # sum volume
    return [buckets[k] for k in sorted(order)]
