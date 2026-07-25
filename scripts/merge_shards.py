#!/usr/bin/env python3
"""
รวมผล shard ของ us-all → 4 ไฟล์ final (docs/us-all.json + -reversals + -levels + -table)

ใช้ตอน publish หลังทุก shard job อัปโหลด artifact `docs/us-all-shard{k}.json` แล้ว
  python scripts/merge_shards.py --universe us-all --shards 8 --artifacts _artifacts

🛡️ guard สำคัญ: ต้องเจอ bundle **ครบทุก shard** ถึงจะเขียน — ขาดแม้ตัวเดียว = SKIP
(คงไฟล์ us-all เดิมไว้) กัน "ข้อมูลตลาดครึ่งใบ" ถ้า shard ใดตาย (mirror publish if:always ของ 4 universe)
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_scan import (  # noqa: E402
    write_output, write_reversals, write_levels, write_table,
)


def _dedupe_results(results):
    """กัน symbol ซ้ำข้าม shard (interleave ควรไม่ซ้ำ แต่กันเหนียว) — เก็บ score สูงสุด"""
    best = {}
    for r in results:
        s = r["symbol"]
        if s not in best or r["score"] > best[s]["score"]:
            best[s] = r
    return list(best.values())


def _dedupe_table(table):
    best = {}
    for r in table:
        s = r[0]
        prev = best.get(s)
        if prev is None or (r[7] or -1) > (prev[7] or -1):
            best[s] = r
    return list(best.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="us-all")
    ap.add_argument("--shards", type=int, required=True, help="จำนวน shard ที่คาดหวัง (ต้องครบ)")
    ap.add_argument("--artifacts", default="_artifacts")
    args = ap.parse_args()
    uni = args.universe

    bundles = sorted(glob.glob(os.path.join(args.artifacts, "**", f"{uni}-shard*.json"),
                               recursive=True))
    # dedupe ตาม shard index (เผื่อ artifact ซ้อน path)
    by_shard = {}
    for b in bundles:
        try:
            d = json.load(open(b, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[merge] อ่าน {b} ไม่ได้: {e}")
            continue
        by_shard[d.get("shard")] = d

    got = len(by_shard)
    if got < args.shards:
        print(f"[merge] SKIP {uni}: เจอ {got}/{args.shards} shard — คงไฟล์เดิม "
              f"(กันข้อมูลตลาดครึ่งใบ)")
        return 0

    results, reversals, levels, table, scanned = [], [], [], [], 0
    for d in by_shard.values():
        results.extend(d.get("results", []))
        reversals.extend(d.get("reversals", []))
        levels.extend(d.get("levels", []))
        table.extend(d.get("table", []))
        scanned += d.get("scanned", 0)

    results = _dedupe_results(results)
    table = _dedupe_table(table)
    results.sort(key=lambda r: r["score"], reverse=True)   # write_output ไม่ sort เอง (scan sort ก่อนเรียก)

    # reuse writer เดิม (stats + schema เหมือน 4 universe เป๊ะ · reversals/levels/table sort ในตัว)
    write_output(uni, results, scanned)
    write_reversals(uni, reversals, scanned)
    write_levels(uni, levels, scanned)
    write_table(uni, table, scanned)
    print(f"[merge] DONE {uni}: {got} shards → {scanned} scanned · "
          f"{len(results)} setups / {len(reversals)} rev / {len(levels)} levels / {len(table)} table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
