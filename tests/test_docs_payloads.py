#!/usr/bin/env python3
"""
🚨 ด่านกัน "ไฟล์ข้อมูลใต้ docs/ หายเงียบ" (บทเรียน 2026-09-20)

เกิดจริง: PR #5 ตั้งใจแก้แค่ screener/levels.py + เทส แต่ commit ติดการลบ
docs/us-all{,-table,-levels,-reversals}.json ไปด้วย (git add -A ในทรีที่ไฟล์ไม่ครบ)
⇒ squash merge พาการลบขึ้น main ⇒ เว็บ /app โหมด Universe ยิง us-all-table.json = 404
ตาราง "ทั้งตลาด" ว่างเปล่า ~2.5 วัน (cron scan ถัดไปคือจันทร์ 22:00Z)

ทำไม CI เดิมไม่จับ: เทสทั้ง 6 ไฟล์เป็นเทส **engine** (คำนวณถูกไหม) ไม่มีตัวไหน
ถามว่า "ของที่ต้องเสิร์ฟยังอยู่ครบไหม" · CI เขียวสนิททั้งที่ผู้ใช้เห็นหน้าว่าง

🔴 อันตรายซ้อน: build_index.py :40-41 ข้าม universe ที่ <u>.json หาย (`continue`)
   ⇒ ถ้า scan รันหลังไฟล์หาย index.json จะ "ลืม" universe นั้นไปเงียบ ๆ
   = อาการหายจากสายตา แต่ผู้ใช้ยังเห็นหน้าว่างเหมือนเดิม

ด่านนี้ตรวจ invariant ไม่ใช่กลไก ⇒ จับได้ทั้งกรณีลบหลุด · merge_shards ล้ม · scan ไม่ครบ

รัน: python tests/test_docs_payloads.py
$0 · ไม่แตะ network
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from build_index import UNIVERSES  # noqa: E402  (ใช้ตัวเดียวกับ builder — เพิ่ม universe แล้วด่านตามเอง)

# ไฟล์ที่ **เว็บ DaddyInvestor ยิงถึงตรง ๆ ด้วยชื่อคงที่** — หายเมื่อไหร่ = หน้าว่างทันที
#   stage-engine.js: SA_BREAKOUT_BASE + '/us-all-table.json' · '/universe-members.json'
#   (repo นั้น private ⇒ ที่นี่ยืนยันไม่ได้ด้วยโค้ด จึงตรึงชื่อไว้เป็นสัญญา — แก้ชื่อต้องแก้ 2 ฝั่งพร้อมกัน)
WEB_FETCHES = ["us-all-table.json", "universe-members.json", "index.json"]

# ต่อ universe: scan / แนวรับ-ต้าน / แพทเทิร์นกลับตัว
PER_UNIVERSE_SUFFIXES = ["", "-levels", "-reversals"]

_pass, _fail = 0, 0


def ok(cond, label, hint=""):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
        print(f"  ✗ {label}")
        if hint:
            print(f"      ↳ {hint}")
    return cond


def load(name):
    path = os.path.join(DOCS, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        print(f"      ↳ {name} พังไม่ใช่ JSON: {e}")
        return False


RESTORE_HINT = ("กู้ด้วย: git checkout <commit ที่ยังมี> -- docs/<ไฟล์>  "
                "(หาได้จาก `git log --diff-filter=D --oneline -- docs/<ไฟล์>`)")


def test_web_fetched_files_exist():
    """ไฟล์ที่เว็บยิงถึงด้วยชื่อคงที่ ต้องมีและ parse ได้"""
    print("═══ ① ไฟล์ที่เว็บยิงถึงตรง ๆ")
    for name in WEB_FETCHES:
        d = load(name)
        ok(d is not None, f"{name} มีอยู่จริง", f"เว็บยิงไฟล์นี้ด้วยชื่อคงที่ — หาย = ผู้ใช้เห็นหน้าว่าง · {RESTORE_HINT}")
        ok(d is not False, f"{name} parse ได้")


def test_every_universe_payload_present():
    """ทุก universe ที่ builder รู้จัก ต้องมีครบ 3 ไฟล์ + มีแถวจริง"""
    print("═══ ② payload ต่อ universe ครบ")
    for u in UNIVERSES:
        for suf in PER_UNIVERSE_SUFFIXES:
            name = f"{u}{suf}.json"
            d = load(name)
            if not ok(d is not None, f"{name} มีอยู่จริง", RESTORE_HINT):
                continue
            if not ok(d is not False, f"{name} parse ได้"):
                continue
            rows = d.get("results")
            ok(isinstance(rows, list), f"{name} มีคีย์ results เป็น list")
            ok(isinstance(rows, list) and len(rows) > 0,
               f"{name} มีแถวจริง (ได้ {len(rows) if isinstance(rows, list) else '?'})",
               "ไฟล์ว่าง = scan ล้มแต่ยัง commit ทับของดี")


def test_index_matches_files_on_disk():
    """index.json ต้องไม่โฆษณา universe ที่ไฟล์ไม่อยู่ (และไม่ลืมตัวที่อยู่)

    นี่คืออาการตรงของบั๊ก 09-20: index บอก us-all scanned 5563 แต่ us-all.json ไม่มีอยู่
    """
    print("═══ ③ index.json ตรงกับไฟล์จริง")
    idx = load("index.json")
    if not ok(idx not in (None, False), "index.json อ่านได้"):
        return
    advertised = set((idx.get("universes") or {}).keys())
    on_disk = {u for u in UNIVERSES if os.path.exists(os.path.join(DOCS, f"{u}.json"))}

    ghosts = advertised - on_disk
    ok(not ghosts, f"index ไม่โฆษณา universe ที่ไฟล์หาย (ผี: {sorted(ghosts) or 'ไม่มี'})",
       "index บอกว่ามี แต่เว็บโหลดไม่ได้ = หน้าว่างแบบไม่มี error · " + RESTORE_HINT)

    forgotten = on_disk - advertised
    ok(not forgotten, f"index ไม่ลืม universe ที่มีไฟล์อยู่ (ลืม: {sorted(forgotten) or 'ไม่มี'})",
       "build_index.py ข้าม universe ที่ <u>.json หาย ⇒ ถ้าไฟล์เคยหายแล้ว scan รันทับ "
       "index จะลืมถาวรโดยไม่มีใครรู้ — รัน python scripts/build_index.py ใหม่")

    for u in advertised & on_disk:
        entry = idx["universes"][u] or {}
        ok(entry.get("scanned") not in (None, 0), f"index[{u}].scanned มีค่า (ได้ {entry.get('scanned')})")


if __name__ == "__main__":
    test_web_fetched_files_exist()
    test_every_universe_payload_present()
    test_index_matches_files_on_disk()
    print(f"\n{'ALL PASS ✅' if not _fail else '💥 FAIL'} — ผ่าน {_pass} / ตก {_fail}")
    sys.exit(1 if _fail else 0)
