// tests/parity_dump.mjs — รัน chart-elliott.js (เครื่องยนต์ที่แผงในแอปใช้จริง) บนชุด candle
// ที่ส่งมา แล้วคายผลเป็น JSON ให้ฝั่ง Python เทียบ
//
// ทำไมต้องมี: ป้าย 🌊 ในตาราง Universe กับแผง Elliott ในหน้าเจาะลึกคือคำตอบของ
//   "คำถามเดียวกัน" ที่ user เห็นสองที่ — ถ้าไม่ตรงกัน = ป้ายโกหก (บั๊กจริง QCRH 08-01)
//   ตัวนี้ + tests/test_parity_vs_chart.py คือ gate ที่กันไม่ให้ drift อีก
//
// ใช้:  node tests/parity_dump.mjs <path/chart-elliott.js> <path/cases.json>
//   cases.json = { cases: [ { name, bars: [{high,low,close}, ...] } ] }
//   stdout     = { "<name>": {"state": "...", "direction": "..."} | null }
//
// เรียก detectWaves(bars, "1d") **ไม่ส่ง opts** — ให้ตรงกับ elliott-panel.js:158 เป๊ะ
// (default maxAgeBars=380 · minSpanShare=0.20) · ส่ง opts เอง = เทสคนละอย่างกับที่ user เห็น

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const [enginePath, casesPath] = process.argv.slice(2);
if (!enginePath || !casesPath) {
  console.error("ใช้: node tests/parity_dump.mjs <chart-elliott.js> <cases.json>");
  process.exit(2);
}

const require = createRequire(import.meta.url);
const EW = require(resolve(enginePath));
const fx = JSON.parse(readFileSync(casesPath, "utf8"));

const out = {};
for (const c of fx.cases) {
  const res = EW.detectWaves(c.bars, "1d");
  out[c.name] = res ? { state: res.state, direction: res.direction } : null;
}
process.stdout.write(JSON.stringify(out));
