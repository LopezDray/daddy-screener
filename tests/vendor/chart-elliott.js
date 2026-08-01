// chart-elliott.js — Elliott Wave structure labelling (เชิงการศึกษา "อ่านโครงสร้างคลื่น")
//
// ⚖️ กฎเหล็ก compliance — ฟีเจอร์นี้ "ชี้ให้เห็นโครงสร้าง" ไม่ใช่การพยากรณ์:
//   ❌ ห้ามมี Entry / Stop-Loss / Take-Profit / เป้าราคา / R:R / "ซื้อ-ขายตอนนี้" / win-rate
//   ❌ **ห้ามวาดเส้นเป้า extension หลังคลื่น 5 จบ (1.0×/1.618×)** — backtest 07-29
//      (686 หุ้น · 2,031 impulses) พบว่าอัตราไปถึงเป้าไม่ต่างจากข้อมูลสุ่ม และเป้าไกลยัง
//      "แพ้" สุ่ม → วาดเป้า = ให้สัญญาที่ข้อมูลของเราเองปฏิเสธ
//   ⚠️ **wave5Range = ข้อยกเว้นที่ owner เคาะเอง (07-29)** — ฉาย "ช่วงที่คลื่น 5 มักจบ"
//      ตอนการนับยังเดินอยู่ · owner เห็นตัวเลขข้อจำกัดครบแล้วและยืนยันว่าต้องการ
//      เงื่อนไขที่ตกลงกัน: วาดเป็น **ช่วง** ไม่ใช่เส้นเดียว · เรียกว่า "ช่วงที่มักจบ"
//      ห้ามเรียกว่าเป้าหมาย/คาดการณ์ · UI ต้องแสดงข้อจำกัด 59.5%/44%/สุ่มได้เท่ากัน คู่เสมอ
//   ✅ โซน fib retracement วาดได้ในฐานะ "บริเวณที่ราคาเคยแวะ" ไม่ใช่เป้าหมาย
//   ✅ ป้ายคลื่น ①-⑤ / Ⓐ-Ⓑ-Ⓒ = "โครงสร้างที่นับได้ตามกติกา" ไม่ใช่ "ราคาจะไปทางนี้"
//   ✅ clarity = "ความชัดของโครงสร้าง" (cap 90) ไม่ใช่ "โอกาสสำเร็จ"
//
// ⚠️ การนับคลื่นของนักวิเคราะห์จริงเป็น discretionary — ไฟล์นี้คือ **นิยามเชิงกลหนึ่งชุด**
//    (ZigZag + กติกาแข็ง R1-R5) ไม่ใช่ Elliott Wave ทั้งศาสตร์ · UI ต้องบอกผู้ใช้ตรงนี้เสมอ
//
// กัน repaint: pivot ที่ยังไม่ "lock" (ราคายังไม่วิ่งกลับเกิน threshold) จะไม่ถูกวาด —
//   ป้ายที่ขึ้นแล้วจึงไม่หายไปเมื่อมีแท่งใหม่ (วินัยเดียวกับ RSI divergence ใน app.js)
//
// Deterministic + reproducible: input เดียวกัน → output เท่ากันทุกครั้ง
//   ห้ามใช้ Date.now()/Math.random() ในไฟล์นี้
//
// 🔁 พอร์ตคู่กับ scripts/elliott_wave_core.py — **แก้สูตรต้องแก้ทั้งสองฝั่ง**
//    parity test: tests/elliott_parity.mjs (golden fixture tests/fixtures/elliott_cases.json)
//
// consume candle shape ของ app.js: { date, open, high, low, close, volume }
// export: window.DaddyElliott (browser) + module.exports (node test)
(function (root) {
  "use strict";

  // ── config ต่อ TF — ต้องตรง PATTERN_CFG ใน chart-patterns.js (ใช้ pivot ชุดเดียวกัน) ──
  const EW_CFG = {
    "1d":  { W: 5, minPct: 0.03, minBars: 120 },
    "1wk": { W: 3, minPct: 0.05, minBars: 80 },
    "1mo": { W: 2, minPct: 0.08, minBars: 40 },
  };
  const TF_ALIAS = { D: "1d", W: "1wk", M: "1mo", "1d": "1d", "1wk": "1wk", "1mo": "1mo" };
  const ATR_MULT = 1.5;

  // โซน fib ที่ "การย่อมักแวะ" — วาดเป็นบริเวณอ้างอิงเท่านั้น ไม่ใช่เป้าหมาย
  const FIB_LEVELS = [0.382, 0.5, 0.618, 0.786];

  // ── ช่วงที่คลื่น 5 "มักจบ" — วัดจริงจาก 686 หุ้น (scripts/elliott_wave5_test.py) ──
  // ความยาวคลื่น 5 เทียบคลื่น 3: กลาง 0.60 เท่า · ช่วงกลาง 50% = 0.45–0.82 เท่า
  //
  // ⚠️ อ่านให้จบก่อนใช้ตัวเลขนี้ — ข้อมูลสุ่มที่ผันผวนเท่ากันให้ค่า **เดียวกันเป๊ะ**
  //    (กลาง 0.60 เท่า · ช่วง 0.43–0.84) → สัดส่วนนี้มาจากวิธีนิยาม "คลื่น" ของ ZigZag
  //    ไม่ใช่พฤติกรรมตลาด · และการนับ 1-2-3-4 เดินต่อจนครบ 5 เพียง 59.5%
  //    UI ต้องเรียกว่า "ช่วงที่มักจบ" เท่านั้น **ห้ามเรียกว่าเป้าหมาย/คาดการณ์ราคา**
  const W5_RANGE = { low: 0.45, mid: 0.618, high: 0.82 };

  function cfgFor(tf) { return EW_CFG[TF_ALIAS[tf] || "1d"]; }

  // ── ATR14 (Wilder) — สำเนาจาก chart-patterns.js เพื่อให้ไฟล์นี้ยืนเดี่ยวใน node test ได้ ──
  function computeATR14(candles, period) {
    period = period || 14;
    const n = candles.length;
    if (n < period + 1) return null;
    const tr = [];
    for (let i = 1; i < n; i++) {
      const h = candles[i].high, l = candles[i].low, pc = candles[i - 1].close;
      tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
    }
    let atr = 0;
    for (let i = 0; i < period; i++) atr += tr[i];
    atr /= period;
    for (let i = period; i < tr.length; i++) atr = (atr * (period - 1) + tr[i]) / period;
    return atr;
  }

  // ── ATR แบบ "ณ เวลานั้น" — atrAt[i] = ATR ที่คำนวณจากแท่ง 0..i เท่านั้น ──
  //
  // ⚠️ จุดที่ไฟล์นี้ **ตั้งใจต่างจาก chart-patterns.js** (ซึ่งใช้ ATR ตัวเดียวจาก series เต็ม):
  //   ATR ตัวเดียวทำให้เกณฑ์ ZigZag ถูก "แก้ย้อนหลัง" ทุกครั้งที่มีแท่งใหม่ → pivot ที่เคย
  //   ผ่านเกณฑ์อาจตกเกณฑ์ → **ป้ายคลื่นที่วาดไปแล้วหายได้** วัดจริง 07-29 บนหุ้นตัวอย่าง 8 ตัว:
  //   โครงสร้างเปลี่ยน 6.1% ของวัน และหายไปเฉยๆ 35 ครั้ง/1,600 แท่ง
  //   สำหรับ pattern detection เดิมไม่เป็นไร (มันคือ "โครงสร้างในกรอบที่เห็นตอนนี้")
  //   แต่ป้ายคลื่นผู้ใช้จำได้และยึดเป็นหลัก — หายแล้วโผล่ = repaint ที่แอปห้ามไว้
  //
  //   ใช้ ATR ณ เวลาที่ pivot เกิด → เกณฑ์นิ่งตลอดกาล ผ่านแล้วผ่านเลย
  function computeATRSeries(candles, period) {
    period = period || 14;
    const n = candles.length;
    const out = new Array(n).fill(null);
    if (n < period + 1) return out;
    const tr = [];
    for (let i = 1; i < n; i++) {
      const h = candles[i].high, l = candles[i].low, pc = candles[i - 1].close;
      tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
    }
    let atr = 0;
    for (let i = 0; i < period; i++) atr += tr[i];
    atr /= period;
    out[period] = atr;                       // tr[0] คือแท่ง 1 → ATR ตัวแรกใช้ได้ที่แท่ง period
    for (let i = period; i < tr.length; i++) {
      atr = (atr * (period - 1) + tr[i]) / period;
      out[i + 1] = atr;
    }
    return out;
  }

  // ATR ที่ "รู้ได้" ณ แท่ง i (ก่อนหน้านั้นยังคำนวณไม่ได้ → ใช้ตัวแรกที่มี)
  function atrAt(atrSeries, i) {
    if (i < atrSeries.length && atrSeries[i] !== null) return atrSeries[i];
    for (let j = Math.min(i, atrSeries.length - 1); j >= 0; j--) {
      if (atrSeries[j] !== null) return atrSeries[j];
    }
    for (let j = 0; j < atrSeries.length; j++) if (atrSeries[j] !== null) return atrSeries[j];
    return null;
  }

  // ── Fractal pivots + ZigZag ──
  // รูปทรง fractal ตรงกับ chart-patterns.js::findPivots เป๊ะ · ต่างที่ threshold ใช้ ATR
  // ณ เวลาของ pivot (ดูเหตุผลด้านบน) แทน ATR ตัวเดียวของทั้ง series
  function findPivots(candles, cfg, atrSeries) {
    const n = candles.length, W = cfg.W, raw = [];
    for (let i = W; i < n - W; i++) {
      let isHigh = true, isLow = true;
      for (let j = i - W; j <= i + W; j++) {
        if (j === i) continue;
        if (j < i) {
          if (candles[j].high >= candles[i].high) isHigh = false;
          if (candles[j].low <= candles[i].low) isLow = false;
        } else {
          if (candles[j].high > candles[i].high) isHigh = false;
          if (candles[j].low < candles[i].low) isLow = false;
        }
      }
      if (isHigh) raw.push({ index: i, price: candles[i].high, type: "H" });
      if (isLow) raw.push({ index: i, price: candles[i].low, type: "L" });
    }
    raw.sort((a, b) => (a.index - b.index) || (a.type === "H" ? -1 : 1));

    const out = [];
    for (const p of raw) {
      if (!out.length) { out.push(p); continue; }
      const last = out[out.length - 1];
      if (p.type !== last.type) {
        // เกณฑ์ยึด ATR ณ แท่งของ pivot ใหม่ = ข้อมูลที่รู้ได้จริงตอนนั้น
        const thr = Math.max(ATR_MULT * atrAt(atrSeries, p.index), cfg.minPct * last.price);
        if (Math.abs(p.price - last.price) >= thr) out.push(p);
      } else if ((p.type === "H" && p.price > last.price) ||
                 (p.type === "L" && p.price < last.price)) {
        out[out.length - 1] = p;
      }
    }
    return out;
  }

  // ── lockIndex — แท่งแรกที่ ZigZag แบบ real-time จะ "ยืนยัน" pivot นี้ ──
  // ป้ายคลื่นวาดได้ก็ต่อเมื่อ lock แล้วเท่านั้น → ป้ายที่ขึ้นแล้วไม่หายเมื่อมีแท่งใหม่
  function lockIndex(candles, pivot, cfg, atrSeries) {
    const thr = Math.max(ATR_MULT * atrAt(atrSeries, pivot.index), cfg.minPct * pivot.price);
    for (let j = pivot.index + cfg.W; j < candles.length; j++) {
      if (pivot.type === "H") { if (pivot.price - candles[j].low >= thr) return j; }
      else { if (candles[j].high - pivot.price >= thr) return j; }
    }
    return null;
  }

  // ── นับ impulse 5 คลื่นตามกติกาแข็งของ Elliott ──
  // ขาขึ้น: L0-H1-L2-H3-L4-H5 · ขาลง: กลับเครื่องหมาย
  //   R1 คลื่น 2 ย่อไม่เกิน 100% ของคลื่น 1 · R2 คลื่น 3 ทำจุดสูงใหม่
  //   R3 คลื่น 3 ไม่ใช่คลื่นที่สั้นที่สุด · R4 คลื่น 4 ไม่กินเขตคลื่น 1 · R5 คลื่น 5 ทำจุดสูงใหม่
  function findImpulses(pivots, opts) {
    const includeTruncated = !!(opts && opts.includeTruncated);
    const out = [];
    for (let i = 0; i + 5 < pivots.length; i++) {
      const six = pivots.slice(i, i + 6);
      const types = six.map((p) => p.type).join("");
      let direction, sgn;
      if (types === "LHLHLH") { direction = "bull"; sgn = 1; }
      else if (types === "HLHLHL") { direction = "bear"; sgn = -1; }
      else continue;
      const [p0, p1, p2, p3, p4, p5] = six.map((p) => p.price);
      const w1 = sgn * (p1 - p0), w3 = sgn * (p3 - p2), w5 = sgn * (p5 - p4);
      if (w1 <= 0 || w3 <= 0 || w5 <= 0) continue;
      const r1 = sgn * (p2 - p0) > 0;
      const r2 = sgn * (p3 - p1) > 0;
      const r3 = w3 > Math.min(w1, w5) - 1e-12;
      const r4 = sgn * (p4 - p1) > 0;
      const r5 = sgn * (p5 - p3) > 0;
      if (!(r1 && r2 && r3 && r4)) continue;
      const truncated = !r5;
      if (truncated && !includeTruncated) continue;
      out.push({
        direction, pivots: six, span: sgn * (p5 - p0),
        lengths: { w1, w3, w5 },
        guideW2InBand: (() => { const r = sgn * (p1 - p2) / w1; return r >= 0.236 && r <= 0.886; })(),
        guideW3Ext: w3 >= w1,
        truncated,
      });
    }
    return out;
  }

  // ── นับ 1-2-3-4 ที่ยัง "เดินอยู่" (ยังไม่มีคลื่น 5) ──
  // ต้องตรงกับ scripts/elliott_wave5_test.py::find_partial_1234 เป๊ะ
  //
  // R3 (คลื่น 3 ไม่สั้นที่สุด) ตรวจได้ไม่ครบตอนนี้ — เทียบคลื่น 1 ได้ แต่เทียบคลื่น 5
  // ไม่ได้เพราะยังไม่เกิด · นี่คือข้อจำกัดจริงของการนับสด ไม่ใช่ข้อบกพร่องของโค้ด
  function findPartial1234(pivots) {
    const out = [];
    for (let i = 0; i + 4 < pivots.length; i++) {
      const five = pivots.slice(i, i + 5);
      const types = five.map((p) => p.type).join("");
      let direction, sgn;
      if (types === "LHLHL") { direction = "bull"; sgn = 1; }
      else if (types === "HLHLH") { direction = "bear"; sgn = -1; }
      else continue;
      const [p0, p1, p2, p3, p4] = five.map((p) => p.price);
      const w1 = sgn * (p1 - p0), w3 = sgn * (p3 - p2);
      if (w1 <= 0 || w3 <= 0) continue;
      if (!(sgn * (p2 - p0) > 0)) continue;   // R1
      if (!(sgn * (p3 - p1) > 0)) continue;   // R2
      if (!(sgn * (p4 - p1) > 0)) continue;   // R4
      out.push({ direction, pivots: five, w1, w3, sgn });
    }
    return out;
  }

  // ── ฉายช่วงที่คลื่น 5 มักจบ จากความยาวคลื่น 3 ──
  // คืน null ถ้าฉายแล้วได้ราคาติดลบ/ศูนย์ (เจอจริงในหุ้นราคาต่ำที่คลื่น 3 ยาวมาก
  // เช่น MTEN ได้ -186 — วาดออกไปก็ไร้ความหมาย ต้องเงียบแทน)
  function projectWave5(pa) {
    const base = pa.pivots[4].price;
    const px = (m) => base + pa.sgn * m * pa.w3;
    const lo = px(W5_RANGE.low), mid = px(W5_RANGE.mid), hi = px(W5_RANGE.high);
    if (lo <= 0 || mid <= 0 || hi <= 0) return null;
    return {
      low: Math.min(lo, hi), mid, high: Math.max(lo, hi),
      mult: W5_RANGE,
    };
  }

  // ── วินิจฉัย "หลังคลื่น 5 จบแล้วเกิดอะไร" — ตอบคำถามที่ผู้ใช้ถามแน่ๆ: "แล้วตอนนี้ล่ะ" ──
  // วัดจริง (07-29, เดินวันต่อวัน 83 หุ้น × 240 วัน): เวลา 69% ของหุ้น-วัน จอโชว์คลื่นที่
  // "จบไปแล้ว" และ 62% ของเวลานั้นจบมาเกิน 4 เดือน — ถ้าไม่อธิบายว่าทำไมไม่มีคลื่นใหม่
  // ผู้ใช้จะคิดว่าเครื่องมือค้าง ทั้งที่จริงราคากำลังแกว่งแบบขาทับกัน (R4 พัง) ซึ่งตรงตาม
  // ทฤษฎีเป๊ะ: ช่วงปรับตัวไม่มีกติกาแข็งให้นับ
  function postWave5Diagnostics(candles, pivots, imp) {
    const h5i = imp.pivots[5].index;
    const startIdx = pivots.findIndex((p) => p.index > h5i);
    const swings = startIdx < 0 ? 0 : pivots.length - startIdx;
    let checked = 0, r4fail = 0;
    if (startIdx >= 0) {
      for (let i = startIdx; i + 4 < pivots.length; i++) {
        const five = pivots.slice(i, i + 5);
        const t = five.map((p) => p.type).join("");
        let sgn;
        if (t === "LHLHL") sgn = 1; else if (t === "HLHLH") sgn = -1; else continue;
        const [p0, p1, p2, p3, p4] = five.map((p) => p.price);
        if (sgn * (p1 - p0) <= 0 || sgn * (p3 - p2) <= 0) continue;
        checked++;
        if (!(sgn * (p4 - p1) > 0)) r4fail++;   // ขาทับกัน = ลายเซ็นของช่วงแกว่ง/ปรับตัว
      }
    }
    return { bars: candles.length - 1 - h5i, swings, checked, r4fail };
  }

  // ── นับ 1-2-3 ที่ยังเดินอยู่ (ขั้นต้นกว่า forming) ──
  // ต้องตรงกับ scripts/elliott_wave5_test.py::find_partial_123 เป๊ะ
  // ⚠️ ขั้นที่เชื่อได้น้อยที่สุด — วัดจริง 686 หุ้น: เจอ 24,186 ครั้ง เดินต่อจนครบ
  //    5 คลื่นเพียง 12.2% (ขั้น 1-2 ยิ่งแย่กว่า: 37,806 ครั้ง รอด 7.9% → ไม่ label เลย)
  //    owner เคาะ 07-29 ให้โชว์ โดยมีเงื่อนไข: UI แปะอัตรารอดคู่ป้ายเสมอ
  function findPartial123(pivots) {
    const out = [];
    for (let i = 0; i + 3 < pivots.length; i++) {
      const four = pivots.slice(i, i + 4);
      const types = four.map((p) => p.type).join("");
      let direction, sgn;
      if (types === "LHLH") { direction = "bull"; sgn = 1; }
      else if (types === "HLHL") { direction = "bear"; sgn = -1; }
      else continue;
      const [p0, p1, p2, p3] = four.map((p) => p.price);
      const w1 = sgn * (p1 - p0), w3 = sgn * (p3 - p2);
      if (w1 <= 0 || w3 <= 0) continue;
      if (!(sgn * (p2 - p0) > 0)) continue;   // R1: คลื่น 2 ย่อไม่เกินคลื่น 1
      if (!(sgn * (p3 - p1) > 0)) continue;   // R2: คลื่น 3 ทำจุดใหม่
      out.push({ direction, pivots: four, w1, w3, sgn });
    }
    return out;
  }

  // ── "ความชัดของโครงสร้าง" 0-90 — ไม่ใช่โอกาสสำเร็จ ──
  // นับเฉพาะสิ่งที่วัดได้จากรูปทรง: ผ่าน guideline ไหม + คลื่น 3 เด่นแค่ไหน + ขนาดคลื่นสมมาตรไหม
  function structureClarity(imp) {
    let s = 40;
    if (imp.guideW2InBand) s += 15;
    if (imp.guideW3Ext) s += 15;
    const { w1, w3, w5 } = imp.lengths;
    if (w3 >= 1.618 * w1) s += 10;              // คลื่น 3 ยืดตามตำรา
    const ratio = Math.min(w1, w5) / Math.max(w1, w5);
    if (ratio >= 0.5) s += 10;                  // คลื่น 1 กับ 5 ใกล้เคียงกัน
    if (imp.truncated) s -= 20;
    return Math.max(10, Math.min(90, s));
  }

  // ── โซน fib ของการย่อ (บริเวณอ้างอิง ไม่ใช่เป้าหมาย) ──
  function fibZone(imp) {
    const six = imp.pivots, sgn = imp.direction === "bull" ? 1 : -1;
    const top = six[5].price;
    return FIB_LEVELS.map((f) => ({ ratio: f, price: top - sgn * f * imp.span }));
  }

  // ── ป้ายการย่อหลัง impulse (Ⓐ-Ⓑ-Ⓒ) — เฉพาะ pivot ที่ lock แล้ว ──
  function labelCorrection(candles, pivots, imp, cfg, atrSeries) {
    const p5 = imp.pivots[5], sgn = imp.direction === "bull" ? 1 : -1;
    let recovery = null;
    for (let j = p5.index + 1; j < candles.length; j++) {
      if (sgn * (candles[j].close - p5.price) > 0) { recovery = j; break; }
    }
    const legs = [];
    for (const p of pivots) {
      if (p.index <= p5.index) continue;
      if (recovery !== null && p.index >= recovery) break;
      const lk = lockIndex(candles, p, cfg, atrSeries);
      if (lk === null || (recovery !== null && lk >= recovery)) continue;
      legs.push({ pivot: p, lock: lk });
    }
    const labels = ["A", "B", "C", "D", "E"];
    return legs.slice(0, 5).map((l, i) => ({ ...l, label: labels[i] }));
  }

  // ── API หลัก — คืนโครงสร้างล่าสุดที่ยืนยันแล้ว พร้อมสำหรับวาด ──
  // opts.maxAgeBars   = ไม่แสดงโครงสร้างที่จบไปนานเกิน (default 380 แท่ง ≈ 1.5 ปีบน daily)
  // opts.minSpanShare = ขนาดคลื่นขั้นต่ำเทียบกรอบราคาที่เห็น (default 0.20)
  //
  //   ทำไมต้องมี: กติกาแข็งของ Elliott ผ่านได้กับคลื่นจิ๋วด้วย — วัดจริง RKLB บนกรอบ
  //   20 เดือน ขาขึ้นใหญ่ 10 เท่าไม่ผ่านกติกา แต่คลื่นเล็กกลางปี 2025 (11% ของกรอบ) ผ่าน
  //   ถ้าวาดตัวนั้นเป็น "โครงสร้างของหุ้นตัวนี้" = ชี้ไปผิดที่ ผู้ใช้เข้าใจผิดทันที
  //   → ไม่ถึงเกณฑ์ = **ไม่วาดเลย** (เงียบดีกว่าเดา · หลักเดียวกับที่ chart-patterns.js
  //   คืน null เมื่อแท่งไม่พอ แทนที่จะเดาคะแนน)
  //   ตั้ง 0 เพื่อปิดตัวกรองนี้ (ใช้ตอนทดสอบ engine ล้วนๆ)
  function detectWaves(candles, tf, opts) {
    const o = opts || {};
    const cfg = cfgFor(tf);
    if (!Array.isArray(candles) || candles.length < cfg.minBars) return null;
    const atrSeries = computeATRSeries(candles);
    if (!atrSeries.some((v) => v !== null)) return null;

    const pivots = findPivots(candles, cfg, atrSeries);
    const maxAge = o.maxAgeBars || 380;
    const minShare = o.minSpanShare === undefined ? 0.20 : o.minSpanShare;
    const n = candles.length;

    // กรอบราคาที่ผู้ใช้เห็นอยู่ — ใช้ตัดสินว่าคลื่น "ใหญ่พอจะเป็นเรื่อง" ไหม
    let lo = Infinity, hi = -Infinity;
    for (const c of candles) { if (c.low < lo) lo = c.low; if (c.high > hi) hi = c.high; }
    const viewRange = hi - lo;

    let best = null;
    for (const imp of findImpulses(pivots)) {
      const lk = lockIndex(candles, imp.pivots[5], cfg, atrSeries);
      if (lk === null) continue;                        // ยังไม่ยืนยัน → ไม่วาด (กัน repaint)
      if (n - imp.pivots[5].index > maxAge) continue;   // เก่าเกินกว่าจะเกี่ยวกับหน้าจอตอนนี้
      if (viewRange > 0 && Math.abs(imp.span) / viewRange < minShare) continue;  // จิ๋วเกินไป
      // ในบรรดาที่ผ่านเกณฑ์ เลือกตัวที่ "จบล่าสุด" — ใกล้สิ่งที่ผู้ใช้กำลังดูที่สุด
      if (!best || imp.pivots[5].index > best.pivots[5].index) { imp.lock = lk; best = imp; }
    }
    // การนับที่ "ยังเดินอยู่" (1-2-3-4 · คลื่น 4 เป็น pivot ล่าสุด) — ผ่านเกณฑ์เดียวกัน
    const lastPivot = pivots.length ? pivots[pivots.length - 1] : null;
    const live = findPartial1234(pivots).filter((pa) =>
      lastPivot && pa.pivots[4].index === lastPivot.index
      && lockIndex(candles, pa.pivots[4], cfg, atrSeries) !== null
      && n - pa.pivots[4].index <= maxAge
      && (viewRange <= 0
          || Math.abs(pa.pivots[4].price - pa.pivots[0].price) / viewRange >= minShare));

    // เลือกอันที่ "ใหม่กว่า" เสมอ — ผู้ใช้ถามว่าตอนนี้อยู่ตรงไหน ไม่ใช่เคยอยู่ตรงไหน
    // (หุ้นที่มีทั้งคลื่นเก่าที่จบแล้ว และ 1-2-3-4 ที่กำลังเดิน ต้องโชว์ตัวที่กำลังเดิน)
    const useLive = live.length
      && (!best || live[live.length - 1].pivots[4].index > best.pivots[5].index);

    if (useLive) {
      const pa = live[live.length - 1];
      const w4price = pa.pivots[4].price;
      const nowPx = candles[candles.length - 1].close;
      // ราคาหลุดคลื่น 4 ไปแล้ว = การนับนี้ใช้ไม่ได้ (กติกา R4 พัง) — ยังแสดง แต่ติดธง
      const invalid = pa.sgn * (nowPx - w4price) < 0;
      return {
        state: invalid ? "invalid" : "forming",
        direction: pa.direction,
        waves: pa.pivots.map((p, i) => ({
          label: String(i), index: p.index, price: p.price, type: p.type,
          date: candles[p.index] && candles[p.index].date,
        })),
        correction: [],
        fib: [],
        // ระดับที่ "การนับจะใช้ไม่ได้" — ตัวเลขนี้ผ่านการทดสอบจริง (40.5% ของการนับ
        // 1-2-3-4 จบลงแบบนี้) ต่างจากเป้าราคาที่ทดสอบแล้วไม่ต่างจากสุ่ม
        invalidationPrice: w4price,
        // ช่วงที่คลื่น 5 มักจบ — เฉพาะตอนการนับยังใช้ได้ (นับพังแล้วฉายต่อ = ไร้ความหมาย)
        wave5Range: invalid ? null : projectWave5(pa),
        clarity: null,
        truncated: false,
        lockIndex: lockIndex(candles, pa.pivots[4], cfg, atrSeries),
      };
    }

    // ── ขั้นต้นกว่า: นับได้ถึงคลื่น 3 (H3/L3 เป็น pivot ล่าสุด) ──
    // โชว์เฉพาะที่ยังไม่พัง (ราคายังไม่หลุดยอดคลื่น 1) — 1-2-3 ที่พังมีเป็นหมื่นเคส
    // โชว์หมด = สแปม · เกณฑ์ขนาด/อายุเดียวกับสถานะอื่น + ต้องใหม่กว่าคลื่นที่จบแล้ว
    if (!useLive) {
      const lastClose = candles[n - 1].close;
      const early = findPartial123(pivots).filter((pa) =>
        lastPivot && pa.pivots[3].index === lastPivot.index
        && lockIndex(candles, pa.pivots[3], cfg, atrSeries) !== null
        && n - pa.pivots[3].index <= maxAge
        && pa.sgn * (lastClose - pa.pivots[1].price) > 0
        && (viewRange <= 0
            || Math.abs(pa.pivots[3].price - pa.pivots[0].price) / viewRange >= minShare)
        && (!best || pa.pivots[3].index > best.pivots[5].index));
      if (early.length) {
        const pa = early[early.length - 1];
        return {
          state: "early",
          direction: pa.direction,
          waves: pa.pivots.map((p, i) => ({
            label: String(i), index: p.index, price: p.price, type: p.type,
            date: candles[p.index] && candles[p.index].date,
          })),
          correction: [],
          fib: [],
          // หลุดยอดคลื่น 1 = คลื่น 4 กินเขตคลื่น 1 (R4) → การนับพังทันที
          invalidationPrice: pa.pivots[1].price,
          clarity: null,
          truncated: false,
          lockIndex: lockIndex(candles, pa.pivots[3], cfg, atrSeries),
        };
      }
    }

    if (!best) return null;

    return {
      state: "complete",
      direction: best.direction,
      waves: best.pivots.map((p, i) => ({
        label: String(i),                                // 0 = จุดเริ่ม · 1-5 = คลื่น
        index: p.index, price: p.price, type: p.type,
        date: candles[p.index] && candles[p.index].date,
      })),
      correction: labelCorrection(candles, pivots, best, cfg, atrSeries).map((c) => ({
        label: c.label, index: c.pivot.index, price: c.pivot.price,
        date: candles[c.pivot.index] && candles[c.pivot.index].date,
      })),
      fib: fibZone(best),
      clarity: structureClarity(best),
      truncated: best.truncated,
      lockIndex: best.lock,
      post5: postWave5Diagnostics(candles, pivots, best),
    };
  }

  // ── ข้อความสำหรับ UI — ทุกบรรทัดผ่านกฎ compliance ด้านบน ──
  const EW_COPY = {
    title: "โครงสร้างคลื่น (Elliott) — เชิงการศึกษา",
    bull: "โครงสร้างขาขึ้น 5 คลื่นที่นับได้ตามกติกา แล้วตามด้วยการย่อ",
    bear: "โครงสร้างขาลง 5 คลื่นที่นับได้ตามกติกา แล้วตามด้วยการเด้ง",
    fib: "เส้นประคือบริเวณที่การย่อมักแวะ (สัดส่วน Fibonacci) — เป็นจุดอ้างอิงสายตา ไม่ใช่เป้าหมายราคา",
    clarity: "ตัวเลข = ความชัดของรูปทรง ไม่ใช่โอกาสที่ราคาจะไปทางใดทางหนึ่ง",
    early: "นับได้ถึงคลื่น 3 — ขั้นที่เชื่อได้น้อยที่สุด: ในอดีตการนับที่มาถึงแค่นี้ " +
      "เดินต่อจนครบ 5 คลื่นเพียงราว 1 ใน 8 · ถ้าราคาหลุดยอดคลื่น 1 การนับใช้ไม่ได้ทันที",
    forming: "นับได้ถึงคลื่น 4 — คลื่น 5 ยังไม่เกิด · เส้นล่างคือระดับที่ถ้าราคาหลุดลงไป " +
      "การนับชุดนี้จะใช้ไม่ได้ ต้องนับใหม่",
    w5range: "แถบคือ \"ช่วงที่คลื่น 5 มักจบ\" จากสถิติในอดีต ไม่ใช่เป้าหมายราคา — " +
      "และต้องอ่านคู่กับข้อจำกัด 2 ข้อ: การนับถึงคลื่น 4 เดินต่อจนครบ 5 ราว 6 ใน 10 ครั้ง " +
      "และข้อมูลสุ่มก็ให้ช่วงเดียวกันนี้ แปลว่าช่วงนี้สะท้อนวิธีนิยามคลื่น ไม่ใช่การพยากรณ์",
    invalid: "การนับชุดนี้ใช้ไม่ได้แล้ว — ราคาหลุดคลื่น 4 ไปก่อนที่คลื่น 5 จะเกิด · " +
      "แสดงไว้ให้เห็นว่าโครงสร้างที่เข้าเกณฑ์ครบก็พังได้เป็นเรื่องปกติ",
    disclaimer:
      "การนับคลื่นเป็นการตีความ — คนละคนนับได้ไม่เหมือนกัน สิ่งที่เห็นนี้คือการนับ" +
      "ด้วยกติกาเชิงกลชุดหนึ่งเท่านั้น เพื่อการศึกษาโครงสร้างกราฟ ไม่ใช่คำแนะนำการลงทุน" +
      "และไม่ได้บอกว่าราคาจะไปทางไหนต่อ",
  };

  const api = {
    detectWaves, findImpulses, findPartial1234, findPartial123, findPivots, projectWave5, W5_RANGE,
    computeATR14, computeATRSeries, atrAt, lockIndex,
    structureClarity, fibZone, EW_CFG, TF_ALIAS, FIB_LEVELS, EW_COPY,
  };
  root.DaddyElliott = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
