// 화면에서 받은 응답을 필요한 칸만 남겨 확장 배경으로 넘기고, 배경의 요청(분개장 [조회], 자금계획 날짜별 조회)을 처리한다.
// 위하고에서는 날짜 고르기·[조회]·왼쪽 자금항목 줄 고르기만 한다. 저장·삭제·입력은 하지 않는다 (읽기 전용).
const KEEP = ["da_date", "no_acct", "nm_yuh", "nm_gubun_bungae", "cd_acctit", "nm_acctit", "mn_bungae1", "mn_bungae2",
  "nm_trade", "cd_trade", "nm_remark", "nm_project", "nm_dept", "nm_emp", "dt_insert", "sq_acttax2"];
const PLAN_KEEP = ["cd_trade", "nm_trade", "mn_fplan", "rmk_fplan", "str_refer", "da_fplan"];
const planCap = [];   // {kind, date, cd_fitem, rows}

window.addEventListener("message", (e) => {
  const m = e.data;
  if (e.source !== window || !m || m.__ceoReport !== 1) return;
  let j;
  try { j = JSON.parse(m.text); } catch (err) { return; }
  if (m.kind === "자금계획목록" || m.kind === "자금계획상세") {
    if (Array.isArray(j)) planCap.push({kind: m.kind, date: m.params.date || "", cd_fitem: m.params.cd_fitem || "", rows: j});
    return;
  }
  if (!j || !Array.isArray(j.data)) return;
  const rows = j.data.map((r) => KEEP.map((k) => (r[k] === undefined || r[k] === null ? "" : r[k])));
  const title = document.title || "";
  chrome.runtime.sendMessage({type: "captured", kind: m.kind, params: m.params, columns: KEEP, rows, tot: j.tot,
    company: (title.split(" - ")[1] || "").trim(), screen: title.split(" - ")[0]});
});

function findQueryButton() {
  const cands = [...document.querySelectorAll("button, a, span, div")].filter((el) =>
    el.offsetParent && el.children.length === 0 && (el.innerText || "").trim() === "조회");
  return cands.length ? (cands[0].closest("button") || cands[0]) : null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, ms, step = 100) {
  for (let t = 0; t < ms; t += step) {
    const v = fn();
    if (v) return v;
    await sleep(step);
  }
  return null;
}

// 자금계획입력 화면의 '계획일자' 달력에서 날짜를 고른다 (달력 단추만 누름).
async function pickDate(y, m, d) {
  const dp = document.querySelector(".WSC_LUXDatePicker");
  if (!dp) throw new Error("계획일자 칸을 찾지 못함");
  let cal = document.querySelector(".WSC_LUXCalendar");
  if (!cal || !cal.offsetParent) {
    dp.querySelector("button.WSC_LUXButton").click();
    cal = await waitFor(() => { const c = document.querySelector(".WSC_LUXCalendar"); return c && c.offsetParent ? c : null; }, 3000);
    if (!cal) throw new Error("달력이 열리지 않음");
  }
  const ym = () => cal.querySelector(".date_day_title").textContent.trim().split(".").map(Number);
  for (let i = 0; i < 30; i++) {
    const [cy, cm] = ym();
    const diff = (y - cy) * 12 + (m - cm);
    if (!diff) break;
    cal.querySelector(diff > 0 ? ".btn_next_mon" : ".btn_prev_mon").click();
    await sleep(150);
  }
  const [cy, cm] = ym();
  if (cy !== y || cm !== m) throw new Error(`달력을 ${y}.${m} 로 옮기지 못함 (기수 범위 밖일 수 있음)`);
  const tds = [...cal.querySelectorAll("td")];
  const first = tds.findIndex((t) => t.textContent.trim() === "1");
  const td = tds.slice(first).find((t) => t.textContent.trim() === String(d));
  if (!td) throw new Error(`${y}.${m}.${d} 칸이 없음`);
  td.querySelector("button").click();
  await sleep(250);
}

function clickGridRow(canvas, i) {
  // 왼쪽 자금항목 표(그림 표)의 i번째 줄을 누른다: 머리글 28px, 줄 28px
  const r = canvas.getBoundingClientRect();
  const x = r.x + Math.min(200, r.width - 20), y = r.y + 42 + 28 * i;
  for (const t of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const E = t.startsWith("pointer") ? PointerEvent : MouseEvent;
    canvas.dispatchEvent(new E(t, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0,
      buttons: t.endsWith("down") ? 1 : 0, pointerId: 1, isPrimary: true}));
  }
}

async function collectDate(key) {
  const y = +key.slice(0, 4), m = +key.slice(4, 6), d = +key.slice(6, 8);
  const start = planCap.length;
  await pickDate(y, m, d);
  const q = findQueryButton();
  if (!q) throw new Error("[조회] 버튼을 찾지 못함");
  const mark = planCap.length;
  q.click();
  const got = await waitFor(() => planCap.slice(mark).some((c) => c.kind === "자금계획목록" && c.date === key), 8000);
  if (!got) throw new Error(`${key} 자금항목 목록이 오지 않음`);
  await sleep(400);   // 날짜를 고를 때 오는 목록 응답까지 다 받은 뒤 마지막 것을 쓴다
  const lists = planCap.slice(start).filter((c) => c.kind === "자금계획목록" && c.date === key);
  const cats = lists[lists.length - 1].rows;
  const out = [];
  if (!cats.length) return out;
  const canvas = document.querySelectorAll("canvas")[1];
  if (!canvas) throw new Error("자금항목 표를 찾지 못함");
  for (let i = 0; i < cats.length; i++) {
    const cat = cats[i];
    const before = planCap.length;
    clickGridRow(canvas, i);
    const det = await waitFor(() => planCap.slice(before).find((c) => c.kind === "자금계획상세" && c.date === key && c.cd_fitem === cat.cd_fitem), 8000);
    if (!det) throw new Error(`${key} ${cat.nm_fitem} 상세가 오지 않음`);
    for (const r of det.rows) out.push([key, cat.yn_inout, cat.cd_fitem, cat.nm_fitem].concat(PLAN_KEEP.map((k) => (r[k] === undefined || r[k] === null ? "" : r[k]))));
  }
  return out;
}

async function collectPlan(dates) {
  await waitFor(() => document.querySelector(".WSC_LUXDatePicker") && document.querySelectorAll("canvas")[1], 20000);
  const rows = [], done = [], errors = [];
  for (const key of dates) {
    try {
      rows.push(...await collectDate(key));
      done.push(key);
    } catch (e) {
      errors.push(String(e.message || e));
      break;   // 한 날이라도 못 받으면 그 달은 쓰지 않는다 (빠진 날을 0원으로 보지 않음)
    }
    chrome.runtime.sendMessage({type: "planProgress", date: key, rows: rows.length});
  }
  const title = document.title || "";
  chrome.runtime.sendMessage({type: "planResult", rows, done, errors, company: (title.split(" - ")[1] || "").trim()});
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === "clickQuery") {
    const b = findQueryButton();
    if (b) b.click();
    reply({ok: !!b});
  }
  if (msg && msg.type === "collectPlan") {
    collectPlan(msg.dates);
    reply({ok: true});
  }
});
