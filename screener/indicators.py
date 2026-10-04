"""indicators.py — ตัวชี้วัดเสริมของ master table (us-all-table.json)

ตอนนี้มีตัวเดียว: RSI 14 วันแบบ Wilder — **สูตรเดียวกับ app.js `rsi()` ของ DaddyInvestor เป๊ะ**
(seed = ค่าเฉลี่ยกำไร/ขาดทุนแบบธรรมดา 14 แท่งแรก แล้ว smoothing แบบ Wilder ต่อ)
⇒ ตัวเลขในตาราง Universe = ตัวเลขที่หน้าเจาะลึกโชว์ (คนละ engine แต่ต้องได้เลขเดียวกัน)

🔴 แก้สูตรที่นี่ = ต้องแก้ app.js คู่กันเสมอ · ล็อกด้วยเลขชุดเดียวกัน 2 ฝั่ง:
   tests/test_rsi.py (ที่นี่) ↔ tests/screener_rsi_parity.mjs (DaddyInvestor) ใช้ซีรีส์+เลขคาดหวังชุดเดียวกัน

CPU ล้วน · 0 fetch เพิ่ม (ใช้ daily candles ที่ scan ดึงมาอยู่แล้ว)
"""

RSI_PERIOD = 14


def rsi_wilder(closes, period=RSI_PERIOD):
    """RSI ล่าสุดของซีรีส์ราคาปิด (Wilder) — คืน None ถ้าแท่งไม่พอ (ต้อง > period)

    พอร์ตตรงจาก app.js rsi(): เคส avgLoss == 0 → 100 (ขึ้นล้วน)
    """
    if not closes or len(closes) <= period:
        return None
    gain = 0.0
    loss = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        if change >= 0:
            gain += change
        else:
            loss -= change
    avg_gain = gain / period
    avg_loss = loss / period
    out = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
        out = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out
