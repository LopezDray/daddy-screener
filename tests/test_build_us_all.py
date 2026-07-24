#!/usr/bin/env python3
"""
Self-test สำหรับ scripts/build_us_all.py (zero-dep — รัน: python tests/test_build_us_all.py)

parse ทำงานบน fixture inline (sandbox ยิง nasdaqtrader.com ไม่ได้ → test แทน network)
ครอบ: map_symbol (class share/warrant/right/unit/preferred), name filter (ADR เก็บ, junk ตัด),
      parse_nasdaq_listed / parse_other_listed (ETF/test/financial-status/NextShares → ตัด)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import build_us_all as b  # noqa: E402

_fail = 0


def check(cond, msg):
    global _fail
    print(f"  {'✅' if cond else '❌'} {msg}")
    if not cond:
        _fail += 1


# fixture: nasdaqlisted.txt (8 คอลัมน์)
NASDAQ_FIXTURE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N
ZZZT|NASDAQ TEST STOCK|Q|Y|N|100|N|N
DEFN|Deficient Co - Common Stock|Q|N|D|100|N|N
NEXS|Some NextShares Fund|Q|N|N|100|N|Y
BABA|Alibaba Group - American Depositary Shares|Q|N|N|100|N|N
File Creation Time: 07242026 22:30|||||"""

# fixture: otherlisted.txt (8 คอลัมน์)
OTHER_FIXTURE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B|N|BRK.B|N|100|N|BRK.B
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
FOO.WS|Foo Corp Warrant|N|FOO.WS|N|100|N|FOO.WS
BAR.U|Bar Acquisition Unit|N|BAR.U|N|100|N|BAR.U
BAZ.R|Baz Corp Right|N|BAZ.R|N|100|N|BAZ.R
GHI.PRA|GHI Preferred Series A|N|GHI.PRA|N|100|N|GHI.PRA
JKL|JKL Industries Common Stock|N|JKL|N|100|N|JKL
File Creation Time: 07242026 22:30|||||"""


def test_map_symbol():
    print("map_symbol:")
    check(b.map_symbol("AAPL") == "AAPL", "plain ticker เก็บ")
    check(b.map_symbol("BRK.B") == "BRK-B", "class share BRK.B → BRK-B")
    check(b.map_symbol("BRK.A") == "BRK-A", "class share BRK.A → BRK-A")
    check(b.map_symbol("FOO.WS") is None, "warrant .WS → ตัด")
    check(b.map_symbol("BAR.U") is None, "unit .U → ตัด")
    check(b.map_symbol("BAZ.R") is None, "right .R → ตัด")
    check(b.map_symbol("BAZ.RT") is None, "right .RT → ตัด")
    check(b.map_symbol("GHI.PRA") is None, "preferred .PRA → ตัด")
    check(b.map_symbol("XYZ.WI") is None, "when-issued .WI → ตัด")
    check(b.map_symbol("TOOLONGSYM") is None, "ยาวเกิน → ตัด")
    check(b.map_symbol("") is None, "ว่าง → None")


def test_name_filter():
    print("name filter:")
    check(b._keep_by_name("Apple Inc. - Common Stock") is True, "common stock เก็บ")
    check(b._keep_by_name("Alibaba - American Depositary Shares") is True, "ADR เก็บ (KEEP_ADR)")
    check(b._keep_by_name("Foo Corp Warrant") is False, "ชื่อ Warrant ตัด")
    check(b._keep_by_name("XYZ 5.5% Notes due 2030") is False, "Notes ตัด")
    check(b._keep_by_name("ABC Preferred Series A") is False, "Preferred ตัด")


def test_parse():
    print("parse_nasdaq_listed:")
    nl = b.parse_nasdaq_listed(NASDAQ_FIXTURE)
    check("AAPL" in nl, "AAPL เก็บ")
    check("BABA" in nl, "BABA (ADR) เก็บ")
    check("QQQ" not in nl, "QQQ (ETF) ตัด")
    check("ZZZT" not in nl, "ZZZT (test issue) ตัด")
    check("DEFN" not in nl, "DEFN (financial status D) ตัด")
    check("NEXS" not in nl, "NEXS (NextShares) ตัด")
    check("File" not in " ".join(nl), "footer 'File Creation Time' ไม่หลุด")

    print("parse_other_listed:")
    ol = b.parse_other_listed(OTHER_FIXTURE)
    check("BRK-B" in ol, "BRK.B → BRK-B เก็บ")
    check("JKL" in ol, "JKL common เก็บ")
    check("SPY" not in ol, "SPY (ETF) ตัด")
    check(not any(x.startswith("FOO") for x in ol), "FOO warrant ตัด")
    check(not any(x.startswith("BAR") for x in ol), "BAR unit ตัด")
    check(not any(x.startswith("GHI") for x in ol), "GHI preferred ตัด")


def main():
    test_map_symbol()
    test_name_filter()
    test_parse()
    print(f"\n{'ALL PASS ✅' if _fail == 0 else f'{_fail} FAIL ❌'}")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
