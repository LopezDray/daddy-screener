#!/usr/bin/env python3
"""
Self-test สำหรับ S2 sharding + merge (zero-net — ไม่ยิง Yahoo)
ครอบ: _parse_shard · shard slicing (interleave disjoint+ครบ) · build_table_row (floor/columns) ·
      merge_shards guard (ขาด shard = skip) + full merge (dedupe + 4 ไฟล์ครบ)
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_scan as rs  # noqa: E402

_fail = 0


def check(cond, msg):
    global _fail
    print(f"  {'✅' if cond else '❌'} {msg}")
    if not cond:
        _fail += 1


def test_parse_shard():
    print("_parse_shard:")
    check(rs._parse_shard("3/8") == (3, 8), "'3/8' → (3,8)")
    check(rs._parse_shard("0/8") == (0, 8), "'0/8' → (0,8)")
    check(rs._parse_shard(None) is None, "None → None (ไม่ shard)")
    for bad in ("8/8", "9/8", "abc", "3/0"):
        try:
            rs._parse_shard(bad)
            check(False, f"'{bad}' ควร error")
        except Exception:
            check(True, f"'{bad}' → error ถูกต้อง")


def test_shard_slicing():
    print("shard slicing (interleave disjoint + ครบ):")
    universe = list(range(100))
    n = 8
    seen, all_ok = set(), True
    for k in range(n):
        part = universe[k::n]
        if set(part) & seen:
            all_ok = False
        seen |= set(part)
    check(all_ok, "8 shard ไม่ทับกัน (disjoint)")
    check(seen == set(universe), "8 shard รวมกัน = ครบ 100 ตัว")
    sizes = [len(universe[k::n]) for k in range(n)]
    check(max(sizes) - min(sizes) <= 1, f"เฉลี่ยเท่ากัน (sizes={sizes})")


def _mk_daily(n=200, close=50.0, vol=500000):
    # candle ปลอมพอให้ผ่าน len>=160 + dv20 = 50*500000=25M ≥ $1M floor
    return [{"time": f"2020-01-{(i % 28) + 1:02d}", "open": close, "high": close + 1,
             "low": close - 1, "close": close, "volume": vol} for i in range(n)]


def test_build_table_row():
    print("build_table_row (floor + columns):")
    daily = _mk_daily()
    weekly = rs.resample(daily, "1wk")
    monthly = rs.resample(daily, "1mo")
    wa = {"stage": 2, "confidence": 70}
    row = rs.build_table_row("AAPL", daily, weekly, monthly, wa, None, None, [])
    check(row is not None, "หุ้นปกติ (dv20 25M, close 50) → มีแถว")
    check(len(row) == len(rs.TABLE_COLUMNS), f"จำนวนคอลัมน์ = {len(rs.TABLE_COLUMNS)}")
    check(row[0] == "AAPL" and row[1] == 50.0, "sym+close ถูก")
    check(row[4] == 2 and row[6] == 70, "w_stage/w_conf จาก wa")
    # floor: penny (close < $1) → None
    penny = _mk_daily(close=0.5, vol=100)
    check(rs.build_table_row("PENNY", penny, rs.resample(penny, "1wk"),
                             rs.resample(penny, "1mo"), None, None, None, []) is None,
          "penny close<$1 → ตัด (None)")
    # floor: low dollar-vol (dv20 < $1M) → None
    lowdv = _mk_daily(close=2.0, vol=100)   # dv=200 << 1M
    check(rs.build_table_row("LOWDV", lowdv, rs.resample(lowdv, "1wk"),
                             rs.resample(lowdv, "1mo"), None, None, None, []) is None,
          "dv20<$1M → ตัด (None)")


def _write_bundle(d, k, results, table):
    payload = {"universe": "us-all", "shard": k, "scanned": 10,
               "generated_at": "2026-07-24T00:00:00Z",
               "results": results, "reversals": [], "levels": [], "table": table}
    with open(os.path.join(d, f"art{k}", "us-all-shard%d.json" % k), "w") as f:
        json.dump(payload, f)


US_FILES = ["us-all.json", "us-all-reversals.json", "us-all-levels.json", "us-all-table.json"]


def _clean_docs():
    for fn in US_FILES:
        p = os.path.join(rs.DOCS_DIR, fn)
        if os.path.exists(p):
            os.remove(p)


def _run_merge(artifacts, shards):
    # write_output ใช้ DOCS_DIR แบบ absolute (repo/docs) → cwd=ROOT เหมือน CI
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "merge_shards.py"),
         "--universe", "us-all", "--shards", str(shards), "--artifacts", artifacts],
        cwd=ROOT, capture_output=True, text=True, env=dict(os.environ))


def test_merge():
    print("merge_shards (guard + full merge):")
    docs_us = os.path.join(rs.DOCS_DIR, "us-all.json")
    _clean_docs()   # เริ่มสะอาด (repo ไม่มี us-all ใน docs อยู่แล้ว)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            art = os.path.join(tmp, "_artifacts")
            # เตรียม 3 shard (จาก 4 ที่คาด) → ควร SKIP
            for k in range(3):
                os.makedirs(os.path.join(art, f"art{k}"))
                _write_bundle(art, k, [{"symbol": f"S{k}", "score": 80 + k, "grade": "A"}],
                              [[f"S{k}", 10.0, 5.0, 2, 2, 2, 70, 80 + k, "B", "s1", None]])
            r = _run_merge(art, 4)
            check("SKIP" in r.stdout and not os.path.exists(docs_us),
                  "ขาด shard (3/4) → SKIP ไม่เขียน us-all.json")

            # เพิ่ม shard ที่ 4 → ครบ → เขียน 4 ไฟล์
            os.makedirs(os.path.join(art, "art3"))
            _write_bundle(art, 3, [{"symbol": "S3", "score": 90, "grade": "A"},
                                   {"symbol": "S0", "score": 50, "grade": "B"}],  # S0 ซ้ำ score ต่ำ
                          [["S3", 20.0, 9.0, 2, 2, 2, 88, 90, "B", "r1", "T"]])
            _run_merge(art, 4)
            check(os.path.exists(docs_us), "ครบ 4 shard → เขียน us-all.json")
            for suffix in US_FILES[1:]:
                check(os.path.exists(os.path.join(rs.DOCS_DIR, suffix)), f"เขียน {suffix}")
            data = json.load(open(docs_us))
            syms = [x["symbol"] for x in data["results"]]
            check(syms.count("S0") == 1, "S0 ซ้ำ → dedupe เหลือ 1")
            check(data["results"][0]["score"] >= data["results"][-1]["score"], "sort score desc")
            s0 = next(x for x in data["results"] if x["symbol"] == "S0")
            check(s0["score"] == 80, "dedupe เก็บ score สูงสุด (80 จาก shard0 ไม่ใช่ 50)")
    finally:
        _clean_docs()   # ล้าง test artifact ไม่ให้ค้าง repo


def main():
    test_parse_shard()
    test_shard_slicing()
    test_build_table_row()
    test_merge()
    print(f"\n{'ALL PASS ✅' if _fail == 0 else f'{_fail} FAIL ❌'}")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
