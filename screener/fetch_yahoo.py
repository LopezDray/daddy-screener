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
from datetime import datetime, timedelta, date as dateobj

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


def _parse_result(result):
    timestamps = result.get("timestamp", [])
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    opens = quote.get("open", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])
    out = []
    for i, ts in enumerate(timestamps):
        try:
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            v = volumes[i] if i < len(volumes) else None
            if o is None or h is None or l is None or c is None:
                continue
            out.append({
                "time": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
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
