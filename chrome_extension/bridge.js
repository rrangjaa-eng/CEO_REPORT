// 화면에서 받은 응답을 필요한 칸만 남겨 확장 배경으로 넘기고, 배경의 요청(분개장 [조회], 자금계획 날짜별 조회)을 처리한다.
// 위하고에서는 날짜 고르기·[조회]·왼쪽 자금항목 줄 고르기만 한다. 저장·삭제·입력은 하지 않는다 (읽기 전용).
const KEEP = ["da_date", "no_acct", "nm_yuh", "nm_gubun_bungae", "cd_acctit", "nm_acctit", "mn_bungae1", "mn_bungae2",
  "nm_trade", "cd_trade", "nm_remark", "nm_project", "nm_dept", "nm_emp", "dt_insert", "sq_acttax2"];
const PLAN_KEEP = ["cd_trade", "nm_trade", "mn_fplan", "rmk_fplan", "str_refer", "da_fplan"];
const BRIDGE_VERSION = 5;   // 배경과 맞춰 본다: 확장을 고친 뒤 새로고침하지 않았으면 배경이 알려 준다
const planCap = [];
let closingArmed = false;   // {kind, date, cd_fitem, rows}

window.addEventListener("message", (e) => {
  const m = e.data;
  if (e.source !== window || !m || m.__ceoReport !== 1) return;
  let j;
  try { j = JSON.parse(m.text); } catch (err) { return; }
  if (m.kind === "결산원본") {   // 결산 자료 받기: 받을 준비 중일 때 온 응답을 그대로 배경으로 (화면 이름·주소 경로만 붙임)
    if (closingArmed) chrome.runtime.sendMessage({type: "closingCaptured", path: m.path, data: j, screen: (document.title || "").split(" - ")[0],
      code: (location.hash.match(/\/account\/([A-Z0-9]+)/) || [])[1] || ""});
    return;
  }
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

// 자금계획입력 화면 '0. 계획월' 보기에서 달을 고른다 (달 목록에서 '2026년 12월' 같은 줄만 누름).
async function pickMonth(y, m) {
  const mp = document.querySelector(".WSC_LUXMonthPicker");
  if (!mp) throw new Error("'계획월' 칸을 찾지 못함 (자금계획입력 화면 보기가 '0. 계획월'이 아님)");
  const label = `${y}년 ${String(m).padStart(2, "0")}월`;
  const find = () => [...document.querySelectorAll("li a, li")].find((e) => e.textContent.trim() === label);
  let item = find();
  if (!item) {
    mp.querySelector("button.WSC_LUXButton").click();
    item = await waitFor(find, 3000);
  }
  if (!item) throw new Error(`달 목록에서 ${label} 을 찾지 못함 (기수 범위 밖일 수 있음)`);
  item.click();
  await sleep(300);
}

// 한 달치: [조회] → 자금항목 목록 → 항목 줄마다 상세(그 달 전체). 줄: [YYYYMMDD, 입금/지급, 항목코드, 항목명, ...PLAN_KEEP]
async function collectMonth(ym) {
  const y = +ym.slice(0, 4), m = +ym.slice(4, 6);
  const start = planCap.length;
  await pickMonth(y, m);
  const q = findQueryButton();
  if (!q) throw new Error("[조회] 버튼을 찾지 못함");
  const mark = planCap.length;
  q.click();
  const got = await waitFor(() => planCap.slice(mark).some((c) => c.kind === "자금계획목록" && c.date === ym), 10000);
  if (!got) throw new Error(`${ym} 자금항목 목록이 오지 않음`);
  await sleep(500);   // 달을 고를 때 오는 목록 응답까지 다 받은 뒤 마지막 것을 쓴다
  const lists = planCap.slice(start).filter((c) => c.kind === "자금계획목록" && c.date === ym);
  const cats = lists[lists.length - 1].rows;
  const out = [];
  if (!cats.length) return out;
  const canvas = document.querySelectorAll("canvas")[1];
  if (!canvas) throw new Error("자금항목 표를 찾지 못함");
  if (42 + 28 * cats.length > canvas.getBoundingClientRect().height) throw new Error(`${ym} 자금항목이 ${cats.length}개라 표에 다 안 보임`);
  for (let i = 0; i < cats.length; i++) {
    const cat = cats[i];
    const before = planCap.length;
    clickGridRow(canvas, i);
    const det = await waitFor(() => planCap.slice(before).find((c) => c.kind === "자금계획상세" && c.date === ym && c.cd_fitem === cat.cd_fitem), 10000);
    if (!det) throw new Error(`${ym} ${cat.nm_fitem} 상세가 오지 않음` + (document.visibilityState === "hidden" ? " (받는 중에 다른 탭으로 옮기면 안 됨)" : ""));
    for (const r of det.rows) {
      const day = String(r.da_fplan || "").padStart(2, "0");
      out.push([ym + day, cat.yn_inout, cat.cd_fitem, cat.nm_fitem].concat(PLAN_KEEP.map((k) => (r[k] === undefined || r[k] === null ? "" : r[k]))));
    }
  }
  return out;
}

async function collectPlan(months) {
  await waitFor(() => document.querySelector(".WSC_LUXMonthPicker, .WSC_LUXDatePicker") && document.querySelectorAll("canvas")[1], 20000);
  const rows = [], done = [], errors = [];
  for (const ym of months) {
    try {
      rows.push(...await collectMonth(ym));
      done.push(ym);
    } catch (e) {
      errors.push(String(e.message || e));
      break;   // 못 받은 달은 쓰지 않는다 (빠진 달을 0원으로 보지 않음)
    }
    chrome.runtime.sendMessage({type: "planProgress", date: ym, rows: rows.length});
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
  if (msg && msg.type === "armClosing") {   // 결산 자료 받기: 지금 열린 화면에서 [조회]를 한 번 누르고 그 응답을 받는다
    closingArmed = true;
    window.postMessage({__ceoArm: 1, ms: msg.ms || 15000}, location.origin);
    setTimeout(() => { closingArmed = false; }, msg.ms || 15000);
    const b = findQueryButton();
    if (b) b.click();
    reply({ok: !!b, screen: (document.title || "").split(" - ")[0], code: (location.hash.match(/\/account\/([A-Z0-9]+)/) || [])[1] || "", v: BRIDGE_VERSION});
  }
  if (msg && msg.type === "collectPlan") {
    collectPlan(msg.months).catch((e) => chrome.runtime.sendMessage({type: "planResult", rows: [], done: [], errors: [String(e.message || e)]}));
    reply({ok: true, v: BRIDGE_VERSION});
  }
});
