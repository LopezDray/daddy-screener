#!/usr/bin/env python3
"""
tests/test_parity_vs_chart.py — 🔴 gate สำคัญที่สุดของ screener/elliott.py

บังคับว่า `screener.elliott.detect_state()` (Python, ใช้ตอน scan ทั้งตลาด) ให้คำตอบ
**ตรงกับ `chart-elliott.js::detectWaves()`** (JS, เครื่องยนต์ที่แผง Elliott ในแอปใช้)
บน candle ชุดเดียวกัน — state + direction ต้องตรง 100% ทุกเคส

ทำไมต้องมี (บทเรียนจริง 2026-08-01)
-----------------------------------
เวอร์ชันแรกของ screener/elliott.py พอร์ตมาแค่ชั้น primitive (ATR/pivots/lock) ซึ่ง
"parity" จริง แล้ว**เขียนชั้นตัดสินใจขึ้นเองใหม่** ผลคือ QCRH ติดป้าย "ถึงคลื่น 4"
ในตาราง Universe ขณะที่แผงบอก "นับครบ 5 คลื่น" — ขัดกันเองบนเว็บเดียวกัน
เทสที่มีตอนนั้น (self-test + สัญญาคอลัมน์) ผ่านหมด เพราะไม่มีอะไรเทียบ "คำตอบสุดท้าย"
⇒ parity ต้องวัดที่ปลายทาง ไม่ใช่ที่ชิ้นส่วน

ชุดเคสที่ใช้
------------
1. หุ้นจริง 8 ตัว × 600 แท่ง จาก DaddyInvestor/tests/fixtures/elliott_cases.json
   (RKLB · VRT · LRCX · COHR · IREN · PL · TSEM · UI)
2. synthetic จาก screener.elliott ที่จงใจครอบทุกสถานะ: forming · early · complete ·
   complete+partial ใหม่กว่า · invalid · ไม่มีโครงสร้าง (ทั้งขาขึ้นและขาลง)

รัน:  python tests/test_parity_vs_chart.py          # $0 ไม่แตะ network
ต้องมี: node ใน PATH + repo DaddyInvestor (ชี้ผ่าน env DADDY_APP_DIR)
⚠️ หาไม่เจอ = **fail** ไม่ใช่ skip — เทสที่ skip เงียบคือเกราะที่ไม่ได้เสียบปลั๊ก
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from screener import elliott as ew                       # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DUMPER = os.path.join(HERE, "parity_dump.mjs")

# ที่ที่อาจเจอ repo DaddyInvestor — env มาก่อนเสมอ
APP_DIR_CANDIDATES = [
    os.environ.get("DADDY_APP_DIR"),
    os.path.join(os.path.dirname(ROOT), "DaddyInvestor"),
    "/home/user/DaddyInvestor",
    os.path.join(ROOT, "_daddyinvestor"),
]

_fails = []


def check(cond, name):
    print(("  ✅ " if cond else "  ❌ ") + name)
    if not cond:
        _fails.append(name)


def die(msg):
    print("\n❌ " + msg)
    sys.exit(1)


def find_app_dir():
    for d in APP_DIR_CANDIDATES:
        if d and os.path.isfile(os.path.join(d, "chart-elliott.js")):
            return d
    die("หา chart-elliott.js ไม่เจอ — ตั้ง env DADDY_APP_DIR ให้ชี้ไปที่ repo DaddyInvestor\n"
        "   (CI: git clone --depth 1 https://github.com/LopezDray/DaddyInvestor)\n"
        "   ที่ลองแล้ว: " + " · ".join(str(d) for d in APP_DIR_CANDIDATES if d))


def bars_of(candles):
    """candle ของ screener → shape ที่ engine ทั้งสองฝั่งอ่านจริง (high/low/close)"""
    return [{"high": c["high"], "low": c["low"], "close": c["close"]} for c in candles]


def synthetic_cases():
    """ครอบทุกสถานะที่ detect_state คืนได้ — ทั้งสองทิศ"""
    def flip(cs):
        return [{"open": 300 - c["open"], "high": 300 - c["low"],
                 "low": 300 - c["high"], "close": 300 - c["close"],
                 "volume": c["volume"]} for c in cs]

    forming = ew._bull_1234()
    early = ew._mk(ew._pad(ew._base_123() + ew._leg(175, 160, 25), 40))
    complete = ew._bull_12345()
    newer = ew._bull_12345_then_1234()
    invalid = ew._bull_1234(tail=ew._leg(140, 158, 22) + ew._leg(158, 133, 4))
    dead = ew._mk(ew._pad(ew._base_123() + ew._leg(175, 125, 30), 40))
    flat = ew._mk([100.0] * 300)
    r4bad = ew._bull_1234(w4=120.0)

    named = {
        "syn_forming": forming,
        "syn_early": early,
        "syn_complete": complete,
        "syn_complete_then_newer": newer,
        "syn_invalid": invalid,
        "syn_dead_123": dead,
        "syn_flat": flat,
        "syn_r4_broken": r4bad,
    }
    out = []
    for name, cs in named.items():
        out.append({"name": name, "bars": bars_of(cs)})
        out.append({"name": name + "_bear", "bars": bars_of(flip(cs))})
    return out


def real_cases(app_dir):
    path = os.path.join(app_dir, "tests", "fixtures", "elliott_cases.json")
    if not os.path.isfile(path):
        die("หา fixture หุ้นจริงไม่เจอ: " + path)
    fx = json.load(open(path, encoding="utf-8"))
    return [{"name": "real_" + c["symbol"], "bars": bars_of(c["bars"])}
            for c in fx["cases"]]


def main():
    if not shutil.which("node"):
        die("ไม่มี node ใน PATH — parity test ต้องรัน chart-elliott.js ของจริง")
    app_dir = find_app_dir()
    engine = os.path.join(app_dir, "chart-elliott.js")
    print(f"engine ฝั่งแอป: {engine}")

    cases = real_cases(app_dir) + synthetic_cases()
    print(f"เคสทั้งหมด: {len(cases)} (หุ้นจริง 8 · synthetic {len(cases) - 8})\n")

    with tempfile.TemporaryDirectory() as td:
        cases_path = os.path.join(td, "cases.json")
        with open(cases_path, "w", encoding="utf-8") as f:
            json.dump({"cases": cases}, f)
        proc = subprocess.run([shutil.which("node"), DUMPER, engine, cases_path],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        die("รัน parity_dump.mjs ไม่ผ่าน:\n" + (proc.stderr or "")[:2000])
    js = json.loads(proc.stdout)

    print("เทียบ Python ↔ JS ทีละเคส (state + direction ต้องตรง):")
    mismatch = []
    for c in cases:
        py = ew.detect_state(c["bars"], "1d")
        py_pair = (py["state"], py["direction"]) if py else None
        j = js.get(c["name"])
        js_pair = (j["state"], j["direction"]) if j else None
        if py_pair != js_pair:
            mismatch.append(f"{c['name']}: py={py_pair} js={js_pair}")
    check(not mismatch,
          f"ทุกเคสตรงกัน ({len(cases)} เคส)"
          + ("" if not mismatch else " — ไม่ตรง: " + " | ".join(mismatch[:8])))

    # ชุด synthetic ต้องกวาดครบทุกสถานะจริง ไม่ใช่ None ยกแผง (ไม่งั้น "ตรงกัน" ไร้ความหมาย)
    seen = set()
    for c in cases:
        j = js.get(c["name"])
        seen.add(j["state"] if j else None)
    for want in ("complete", "forming", "early"):
        check(want in seen, f"ชุดเคสครอบสถานะ '{want}' จริง (ไม่ใช่เทสที่ผ่านเพราะว่างเปล่า)")

    # สัญญาที่ป้าย 🌊 พึ่งอยู่: มีแค่ forming/early เท่านั้นที่ได้ code
    print("\nสัญญาของคอลัมน์ ew (map state → code):")
    for c in cases:
        py = ew.detect_state(c["bars"], "1d")
        if py is None:
            continue
        code = py["code"]
        st = py["state"]
        good = ((st == "forming" and code in ("4u", "4d"))
                or (st == "early" and code in ("3u", "3d"))
                or (st in ("complete", "invalid") and code is None))
        if not good:
            check(False, f"{c['name']}: state={st} แต่ code={code!r}")
            break
    else:
        check(True, "forming→4x · early→3x · complete/invalid→None ครบทุกเคส")


if __name__ == "__main__":
    main()
    print("\n" + ("ALL PASS ✅ — ป้าย 🌊 พูดตรงกับแผง Elliott"
                  if not _fails else f"FAIL ❌ ({len(_fails)}): " + " · ".join(_fails)))
    sys.exit(1 if _fails else 0)
