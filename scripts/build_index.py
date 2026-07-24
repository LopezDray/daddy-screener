#!/usr/bin/env python3
"""สร้าง docs/index.json = meta รวมของทุก universe (อัปเดตล่าสุด + count เกรด)"""

import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
UNIVERSES = ["nasdaq100", "sp500", "sp400", "sp600", "us-all"]


def main():
    index = {"generated_at": datetime.now(timezone.utc).isoformat(), "universes": {}}
    for u in UNIVERSES:
        path = os.path.join(DOCS, f"{u}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        st = data.get("stats", {})
        entry = {
            "updated": data.get("generated_at"),
            "scanned": st.get("scanned"),
            "grade_a": st.get("grade_a"),
            "grade_b": st.get("grade_b"),
        }
        lpath = os.path.join(DOCS, f"{u}-levels.json")
        if os.path.exists(lpath):
            with open(lpath, encoding="utf-8") as f:
                lst = json.load(f).get("stats", {})
            entry["near_levels"] = lst.get("found")
        index["universes"][u] = entry
    with open(os.path.join(DOCS, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"[index] wrote index.json — {len(index['universes'])} universes")


if __name__ == "__main__":
    main()
