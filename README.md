# daddy-screener

Compute node ของ **daddyinvestor.net** — สแกนหุ้น 3 universe (NASDAQ100 + S&P500 + Russell2000)
หา setup **"Breakout เพื่อถือ + ออมยาว (DCA)"** โดยผสม Stan Weinstein Stage Analysis กับ Volume Profile

รันบน **GitHub Actions ของ public repo** → ฟรีไม่จำกัดนาที · ดึงราคาจาก Yahoo Finance (ฟรี ไม่ใช้ key)
→ เขียนผลเป็น **static JSON บน GitHub Pages** → เว็บหลัก `fetch()` ไปแสดง

```
cron 22:00 UTC ─► Yahoo (ฟรี) ─► stage + volume profile + score ─► docs/<universe>.json ─► GitHub Pages ─► daddyinvestor.net
```

**ทำไมแยก repo:** Actions ฟรีไม่จำกัด (public) · IP แยกจาก production (Yahoo บล็อกไม่ลามเว็บหลัก) · egress Supabase = 0

---

## Setup (ครั้งเดียว)

1. สร้าง repo นี้เป็น **Public**
2. **Settings → Pages** → Source = `Deploy from a branch` → branch `main`, folder `/docs` → Save
3. **Settings → Actions → General** → Workflow permissions = **Read and write** (ให้ bot commit ผลได้)
4. รันครั้งแรก: Actions → *Update Universes* → Run (เติม S&P500/Russell2000 ให้ครบ) → จากนั้น *Breakout DCA Screener* → Run

ผลจะอยู่ที่:
```
https://<user>.github.io/daddy-screener/index.json
https://<user>.github.io/daddy-screener/nasdaq100.json
https://<user>.github.io/daddy-screener/sp500.json
https://<user>.github.io/daddy-screener/russell2000.json
```

> **ไม่ต้องตั้ง Secret ใด ๆ** — ไม่แตะ Supabase/FMP

---

## กลยุทธ์ (ย่อ)

| ชั้น | เกณฑ์ | บทบาท |
|---|---|---|
| **Hard gates** | Weekly Stage 2 (conf≥60) · Monthly ∈{1,2} · ราคา>MA30w slope>0 · avg\$vol 20d≥\$10M · ≥60 สัปดาห์ | ประตูเทรนด์ + สภาพคล่องสำหรับ DCA |
| **Breakout** | close รายสัปดาห์ > base high (26w) · > VAH ของ Volume Profile · vol≥1.5× avg10w | นิยาม breakout เป็นกลาง ใช้ weekly close กัน false |
| **Volume Profile** | POC/VAL/VAH ของฐาน + overhead supply | ยืนยัน breakout + หา "โซนออม" (VAL–POC) |
| **RS** | ราคา/ดัชนีแม่ (QQQ/SPY/IWM) 12w new-high | ชนะตลาดของ universe ตัวเอง |

รวมเป็นคะแนน 0–100 → **A ≥80 (เริ่มออมได้)** · **B 65–79 (รอย่อเข้าโซน)** · ต่ำกว่า 65 ไม่เก็บ

รายละเอียดเกณฑ์/น้ำหนัก → `screener/scoring.py` (จูน threshold ที่หัวไฟล์)

---

## โครงสร้าง

```
screener/
  fetch_yahoo.py     ดึงแท่งเทียน+volume, resample week/month, retry/backoff
  stage.py           Stan Weinstein stage (faithful port จากเว็บหลัก — ห้ามแก้สูตรเดี่ยว)
  volume_profile.py  POC + Value Area (70%) + overhead supply (port app.js)
  scoring.py         hard gates + breakout + VP + RS → score/grade
  universes/*.json   รายชื่อหุ้นต่อ universe
scripts/
  update_universes.py  refresh S&P500 (Wikipedia) + Russell2000 (iShares IWM CSV)
  build_index.py       รวม meta → docs/index.json
docs/                  ผลลัพธ์ (GitHub Pages เสิร์ฟจากตรงนี้)
run_scan.py            entrypoint: python run_scan.py --universe nasdaq100
```

## รันในเครื่อง (เทส)

```bash
python run_scan.py --universe nasdaq100 --limit 20 --throttle 0.3
cat docs/nasdaq100.json
```

---

## Guardrails

- **stand-alone** — ห้าม import อะไรจาก repo DaddyInvestor (แยก IP/โค้ด เหมือน evidence-gate)
- **ไม่มี secret ในโค้ด** — repo public
- `stage.py` เป็น faithful port ของ `stage-analysis.html` / `scan_nasdaq_screener.py` — แก้สูตรต้อง sync กับเว็บหลัก
- ผลลัพธ์ = สัญญาณ *เริ่ม* ออม ไม่ใช่คำแนะนำ all-in · กติกาหยุดออม = weekly หลุด Stage 2

## ⚠️ ข้อควรระวัง

- **Survivorship bias** — universe = สมาชิกดัชนี *ปัจจุบัน* ใช้คัดหุ้นวันนี้ได้ **ห้ามเอาไป backtest ย้อนหลัง**
- **Yahoo rate-limit** — มี retry+host fallback+throttle · ถ้าโดนเหมาแบน IP GitHub บางวัน → ใช้ JSON เดิม (ไม่พัง)
- **Russell2000** — microcap สภาพคล่องต่ำ/data มีรู → gate สภาพคล่องกรองออกเยอะ (คาดเหลือหลักสิบ = ปกติ)
