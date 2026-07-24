#!/usr/bin/env python3
"""
สร้าง universe "us-all" = หุ้นสามัญ US ทั้งตลาด (~6-7k ตัว) จาก NASDAQ Trader symbol directory — $0 ไม่ใช้ FMP

แหล่ง (official, ฟรี, อัปเดตรายวัน, ไม่บล็อก datacenter-IP เหมือน iShares):
  nasdaqlisted.txt  = หุ้นที่ list บน Nasdaq
  otherlisted.txt   = หุ้นที่ list บน NYSE / NYSE American / NYSE Arca / BATS / IEX ฯลฯ

กรอง junk ให้เหลือหุ้นสามัญที่เทรดได้จริง (คุณภาพ scan สูงขึ้น + ลด call เปล่า):
  - ตัด ETF / Test Issue / NextShares (ไม่ใช่หุ้นสามัญ)
  - ตัด Financial Status ที่ไม่ใช่ Normal ('N') = deficient/delinquent/bankrupt (ข้อมูลมักโหว่)
  - ตัด warrants / rights / units / preferreds / notes / when-issued (ทั้ง suffix และ regex ชื่อ)
  - **เก็บ ADR ไว้** (TSM/BABA ฯลฯ = หุ้นสามัญต่างชาติที่เทรดใน US, owner อยากได้ "ทั้งตลาด")
    → ถ้าอยากตัด ADR ภายหลัง = ตั้ง KEEP_ADR=False บรรทัดเดียว

Yahoo symbol mapping: class share ใช้จุด (BRK.B) → Yahoo ใช้ขีด (BRK-B) เหมือน update_universes.py

Guard: ถ้าดึง/parse ได้จำนวนน้อยผิดปกติ (< FLOOR) → คงไฟล์เดิม (ไม่ทับด้วยของพัง) — pattern เดียวกับ _refresh
"""

import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_DIR = os.path.join(ROOT, "screener", "universes")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; daddy-screener/1.0)"}

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

NAME = "us-all"
FLOOR = 5000          # ต่ำกว่านี้ = ดึงพัง คงไฟล์เดิม
KEEP_ADR = True       # ADR = หุ้นสามัญต่างชาติเทรด US → เก็บ (พลิก False ถ้าอยากตัด)

# suffix (หลังจุด) ที่ = ไม่ใช่หุ้นสามัญ → ตัด
_WARRANT = re.compile(r"^WS")             # .WS, .WSA, .WSB ...
_RIGHT = re.compile(r"^R(T)?$")           # .R, .RT
_UNIT = re.compile(r"^U$")                # .U
_PREFERRED = re.compile(r"^PR")           # .PRA, .PRB ... (preferred)
_WHENISSUED = re.compile(r"^WI$")         # .WI
_CLASS = re.compile(r"^[A-Z]$")           # .A, .B (class share = เก็บ, map → -A/-B)

# ชื่อหลักทรัพย์ที่ = ไม่ใช่หุ้นสามัญ (กันเคสที่ suffix ไม่ชัด)
_NAME_JUNK = re.compile(
    r"\b(warrant|right|unit|preferred|depositary|debenture|note|"
    r"when[-\s]?issued|contingent value)",
    re.I,
)
_NAME_ADR = re.compile(r"\b(ADR|American Depositary|ADS)\b", re.I)

_VALID_SYMBOL = re.compile(r"^[A-Z][A-Z\-]{0,6}$")


def _get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")


def map_symbol(sym):
    """แปลง symbol NASDAQ Trader → รูปแบบ Yahoo · คืน None ถ้า = ไม่ใช่หุ้นสามัญ / รูปแบบใช้ไม่ได้"""
    sym = sym.strip().upper()
    if not sym:
        return None
    # แยก separator ที่พบ: '.' (มาตรฐาน otherlisted), '$'/'=' (บาง feed) → เป็น '.'
    norm = sym.replace("$", ".").replace("=", ".")
    if "." in norm:
        base, _, suffix = norm.partition(".")
        # เช็ค junk suffix ก่อน class — เพราะ U (unit) / R (right) เป็นตัวอักษรเดี่ยว
        # ชนกับ pattern class share [A-Z] · unit/right ต้องชนะ (class จริงเกือบทั้งหมด = A/B/C)
        if (_WARRANT.match(suffix) or _RIGHT.match(suffix) or _UNIT.match(suffix)
                or _PREFERRED.match(suffix) or _WHENISSUED.match(suffix)):
            return None                       # warrant/right/unit/preferred/WI → ตัด
        if _CLASS.match(suffix):
            norm = f"{base}-{suffix}"        # class share: BRK.B → BRK-B (เก็บ)
        else:
            return None                       # suffix ไม่รู้จัก → ตัด (conservative)
    return norm if _VALID_SYMBOL.match(norm) else None


def _keep_by_name(name):
    """คืน False ถ้าชื่อบ่งชี้ว่าไม่ใช่หุ้นสามัญ · ADR = เก็บ (ถ้า KEEP_ADR)"""
    if _NAME_ADR.search(name):
        return KEEP_ADR
    return not _NAME_JUNK.search(name)


def _parse(text, symbol_idx, etf_idx, test_idx, name_idx, fin_idx=None, nextshares_idx=None):
    """parse pipe-delimited NASDAQ Trader file → list[symbol] (กรองแล้ว)
    row สุดท้าย 'File Creation Time...' = ข้าม (ไม่มี field ครบ)"""
    need = max(i for i in (symbol_idx, etf_idx, test_idx, name_idx, fin_idx, nextshares_idx)
               if i is not None)
    out = []
    for ln in text.splitlines()[1:]:           # ข้าม header
        if ln.startswith("File Creation Time"):
            continue
        cols = ln.split("|")
        if len(cols) <= need:
            continue
        if cols[etf_idx].strip().upper() == "Y":       # ETF → ตัด
            continue
        if cols[test_idx].strip().upper() == "Y":      # test issue → ตัด
            continue
        if nextshares_idx is not None and cols[nextshares_idx].strip().upper() == "Y":
            continue                                    # NextShares (ETMF) → ตัด
        if fin_idx is not None and cols[fin_idx].strip().upper() not in ("N", ""):
            continue                                    # Financial Status ไม่ Normal → ตัด
        if not _keep_by_name(cols[name_idx].strip()):
            continue
        sym = map_symbol(cols[symbol_idx])
        if sym:
            out.append(sym)
    return out


def parse_nasdaq_listed(text):
    # Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
    return _parse(text, symbol_idx=0, etf_idx=6, test_idx=3, name_idx=1, fin_idx=4, nextshares_idx=7)


def parse_other_listed(text):
    # ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
    return _parse(text, symbol_idx=0, etf_idx=4, test_idx=6, name_idx=1)


def _dedupe(items):
    seen, out = set(), []
    for s in items:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def build():
    nl = parse_nasdaq_listed(_get(NASDAQ_LISTED_URL))
    ol = parse_other_listed(_get(OTHER_LISTED_URL))
    syms = _dedupe(nl + ol)
    syms.sort()
    return syms


def _write(symbols):
    path = os.path.join(UNIVERSE_DIR, f"{NAME}.json")
    payload = [{"symbol": s, "sector": None} for s in symbols]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"universe": NAME, "count": len(payload), "symbols": payload},
                  f, ensure_ascii=False, indent=1)
    print(f"[universe] wrote {NAME}: {len(payload)} symbols")


def main():
    try:
        syms = build()
    except Exception as e:  # noqa: BLE001
        print(f"[universe] {NAME} error: {e} (คงไฟล์เดิม)")
        return
    if len(syms) < FLOOR:
        print(f"[universe] SKIP {NAME}: got {len(syms)} < {FLOOR} (คงไฟล์เดิม กันทับของพัง)")
        return
    _write(syms)


if __name__ == "__main__":
    main()
