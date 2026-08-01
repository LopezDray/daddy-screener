# tests/vendor — สำเนา engine ฝั่งแอปไว้ใช้เทียบใน CI

## `chart-elliott.js`

**คัดลอกมาเฉยๆ ห้ามแก้** — ต้นฉบับอยู่ที่ `LopezDray/DaddyInvestor:chart-elliott.js`
(private repo) ซึ่งเป็นเครื่องยนต์ที่ **แผง Elliott ในแอปใช้จริง**

| | |
|---|---|
| ต้นทาง | `LopezDray/DaddyInvestor` @ `chart-elliott.js` |
| commit ล่าสุดของไฟล์ต้นทาง | `4fe405a` (PR #1071) |
| คัดลอกเมื่อ | 2026-08-01 |
| sha256 | ดู `chart-elliott.js.sha256` |

### ทำไมต้อง vendor แทนที่จะ clone ตอน CI

DaddyInvestor เป็น **private repo** → `git clone` แบบไม่มี token ใน Actions ของ
daddy-screener (public) ล้มด้วย `could not read Username` และการยัด PAT ข้าม repo
เพื่อรันเทสไม่คุ้มความเสี่ยง ⇒ ใช้สำเนาแทน

### แล้วจับ drift ยังไง (สำคัญ — สำเนาเก่าเป็นได้)

**สองทิศ คนละที่:**

1. **Python เพี้ยนจาก JS** → `tests/test_parity_vs_chart.py` ใน repo นี้ (รันกับสำเนานี้)
   จับได้ทุก PR
2. **JS เปลี่ยนแล้ว Python ไม่ตาม** → CI ฝั่ง **DaddyInvestor** (`tests.yml` job
   `screener-elliott-parity`) clone daddy-screener (public — ทำได้) แล้วรันเทสตัวเดียวกัน
   โดยชี้ `DADDY_APP_DIR` ไปที่ **chart-elliott.js ตัวจริง** ⇒ แก้ engine ฝั่งแอปแล้ว
   screener ยังไม่ตาม = CI ฝั่งแอปแดงทันที

⇒ สำเนานี้เก่าได้โดยไม่อันตราย เพราะ "ความจริง" ถูกตรวจจากฝั่งที่ถือของจริงอยู่แล้ว

### อัปเดตสำเนา (ทำเมื่อ CI ฝั่งแอปฟ้อง หรือรู้ว่า engine เปลี่ยน)

```bash
cp <DaddyInvestor>/chart-elliott.js tests/vendor/chart-elliott.js
sha256sum tests/vendor/chart-elliott.js | awk '{print $1}' > tests/vendor/chart-elliott.js.sha256
python tests/test_parity_vs_chart.py     # ต้องเขียวก่อน commit
```
