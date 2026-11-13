// 화면에서 받은 응답을 필요한 칸만 남겨 확장 배경으로 넘기고, 배경의 요청(분개장 [조회], 자금계획 날짜별 조회)을 처리한다.
// 위하고에서는 날짜 고르기·[조회]·왼쪽 자금항목 줄 고르기만 한다. 저장·삭제·입력은 하지 않는다 (읽기 전용).
const KEEP = ["da_date", "no_acct", "nm_yuh", "nm_gubun_bungae", "cd_acctit", "nm_acctit", "mn_bungae1", "mn_bungae2",
  "nm_trade", "cd_trade", "nm_remark", "nm_project", "nm_dept", "nm_emp", "dt_insert", "sq_acttax2"];
const PLAN_KEEP = ["cd_trade", "nm_trade", "mn_fplan", "rmk_fplan", "str_refer", "da_fplan"];
const BRIDGE_VERSION = 6;   // 배경과 맞춰 본다: 확장을 고친 뒤 새로고침하지 않았으면 배경이 알려 준다
const planCap = [];
let closingArmed = false;   // {kind, date, cd_fitem, rows}
let autoCap = null;   // 결산·인사급여 자동 받기: 이 화면 코드의 응답만 모은다 [{path, data}]

// 개인정보·비밀값 빼기 (사용자 2026-11-12): 비밀번호·전화·메일·주소·계좌는 버리고, 주민번호는 생년월일-성별 자리(YYMMDD-G)만 남긴다.
const DROP_KEY = /(^pw_|passw|^cel_|^tel_|^em_|email|^zip|^add_|addr|bank|deposit|card_no|no_card|account_no|account_holder|profile_url|^ip_|token|secret)/i;
const ID_KEY = /(social|no_res|jumin)/i;
function scrub(v, key = "") {
  if (Array.isArray(v)) return v.map((x) => scrub(x));
  if (v && typeof v === "object") {
    const o = {};
    for (const [k, x] of Object.entries(v)) if (!DROP_KEY.test(k)) o[k] = scrub(x, k);
    return o;
  }
  if (typeof v === "string" && ID_KEY.test(key)) {
    const d = v.replace(/\D/g, "");
    return d.length >= 7 ? `${d.slice(0, 6)}-${d[6]}` : d.slice(0, 6);
  }
  return v;
}
const screenCode = () => (location.hash.match(/\/(?:account|humanresource)\/([A-Z0-9]+)/) || [])[1] || "";

window.addEventListener("message", (e) => {
  const m = e.data;
  if (e.source !== window || !m || m.__ceoReport !== 1) return;
  let j;
  try { j = JSON.parse(m.text); } catch (err) { return; }
  if (m.kind === "결산원본") {   // 결산 자료 받기: 받을 준비 중일 때 온 응답을 배경으로 (화면 이름·주소 경로만 붙임, 회사정보 응답은 버림)
    if (/companyinfo/i.test(m.path)) return;
    if (autoCap && m.path.toLowerCase().includes("/" + autoCap.code.toLowerCase() + "/")) autoCap.got.push({path: m.path, data: scrub(j)});
    if (closingArmed) chrome.runtime.sendMessage({type: "closingCaptured", path: m.path, data: scrub(j), screen: (document.title || "").split(" - ")[0],
      code: screenCode()});
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

// 위하고 안내 창 중 '불러오기'·'조회 조건 누락' 같은 읽기용 창만 [확인]을 누른다. 저장·삭제를 묻는 창은 건드리지 않는다.
function clickLoadDialog() {
  const oks = [...document.querySelectorAll("button, a, span, div")].filter((el) =>
    el.getBoundingClientRect().width > 0 && el.children.length === 0 && (el.innerText || "").trim() === "확인");
  for (const b of oks) {
    let box = b;
    for (let i = 0; i < 8 && box; i++) {
      box = box.parentElement;
      const t = box ? (box.innerText || "") : "";
      if (t.length > 400) break;
      if (/저장하시겠|삭제|변경하시겠|마감/.test(t)) return "";
      if (/불러오시겠/.test(t)) { (b.closest("button") || b).click(); return "불러오기"; }
    }
  }
  return "";
}

// 사업·기타소득조회 조건 채우기: 귀속년월 달력에서 1월~12월을 고르고, 소득자 코드도움을 열어 머리줄 체크(전체)를 누른 뒤 [확인].
// 조회 조건만 고른다 (자료는 바꾸지 않음).
const vis = (e) => e.getBoundingClientRect().width > 0;
function pointerClick(el, x, y) {
  for (const t of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const E = t.startsWith("pointer") ? PointerEvent : MouseEvent;
    el.dispatchEvent(new E(t, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0,
      buttons: t.endsWith("down") ? 1 : 0, pointerId: 1, isPrimary: true, view: window}));
  }
}
async function fillEarners() {
  const dateBtn = await waitFor(() => [...document.querySelectorAll("span.icon_datefield")].filter(vis)[0], 8000);
  if (!dateBtn) throw new Error("귀속년월 칸을 찾지 못함");
  (dateBtn.closest("button") || dateBtn).click();
  const cal = await waitFor(() => [...document.querySelectorAll(".LS_calendar")].find(vis), 3000);
  if (!cal) throw new Error("귀속년월 달력이 열리지 않음");
  const boxes = [...cal.querySelectorAll(".LS_date_day_bx")];
  const pick = (b, m) => [...b.querySelectorAll("td.date_day button")].find((x) => x.textContent.trim() === m + "월");
  const a = pick(boxes[0], 1), z = pick(boxes[boxes.length - 1], 12);
  if (!a || !z) throw new Error("달력에서 1월·12월을 찾지 못함");
  a.click(); await sleep(150); z.click(); await sleep(150);
  [...cal.querySelectorAll("button")].find((x) => x.textContent.trim() === "확인").click();
  await sleep(400);
  const field = [...document.querySelectorAll(".LS_ngh_input2.righticon")].filter(vis).find((e) => !e.classList.contains("datedisabled") && e.querySelector("button"));
  if (!field) throw new Error("소득자 칸을 찾지 못함");
  field.querySelector("button").click();
  const title = await waitFor(() => [...document.querySelectorAll("*")].find((e) => e.children.length === 0 && /코드도움$/.test(e.textContent.trim()) && vis(e)), 5000);
  if (!title) throw new Error("소득자 코드도움 창이 열리지 않음");
  let dlg = title;
  while (dlg && !dlg.querySelector("canvas")) dlg = dlg.parentElement;
  const canvas = dlg && [...dlg.querySelectorAll("canvas")].find(vis);
  if (!canvas) throw new Error("소득자 목록 표를 찾지 못함");
  await sleep(600);   // 목록이 그려진 뒤
  const r = canvas.getBoundingClientRect();
  pointerClick(canvas, r.x + 11, r.y + 10);   // 머리줄 체크 = 전체 선택
  await sleep(400);
  const ok = [...dlg.querySelectorAll("button")].filter(vis).find((b) => /^확인/.test(b.textContent.trim()));
  if (!ok) throw new Error("코드도움 [확인]을 찾지 못함");
  ok.click();
  await sleep(500);
}

// 소득자별 근로소득원천징수부: [조회] 뒤 왼쪽 사원 표(그림 표, 머리줄·줄 28px)를 한 줄씩 눌러 사원마다 달별 소득세 응답을 받는다.
// 받은 응답에는 사원코드가 없어서, 누른 뒤 오른쪽 '사원코드' 칸 값을 붙인다. 화면을 보기만 한다.
function panelEmpCode() {
  const lab = [...document.querySelectorAll("*")].find((e) => e.children.length === 0 && e.textContent.trim() === "사원코드" && vis(e));
  let p = lab;
  for (let i = 0; i < 3 && p; i++) {
    p = p.parentElement;
    const m = ((p && p.innerText) || "").match(/사원코드\s*(\d{3,})/);
    if (m) return m[1];
  }
  return "";
}
async function walkEmployeeRows(subPath) {
  const list = await waitFor(() => autoCap.got.find((g) => Array.isArray(g.data) && g.data.length && g.data[0].cd_emp !== undefined), 10000);
  if (!list) throw new Error("사원 목록이 오지 않음");
  const n = list.data.length;
  const canvas = [...document.querySelectorAll("canvas")].filter(vis)[0];
  if (!canvas) throw new Error("사원 표를 찾지 못함");
  const r = canvas.getBoundingClientRect();
  if (42 + 28 * n > r.height) throw new Error(`사원이 ${n}명이라 표에 다 안 보임`);
  for (let i = 0; i < n; i++) {
    const before = autoCap.got.length;
    pointerClick(canvas, r.x + Math.min(150, r.width - 20), r.y + 42 + 28 * i);
    const g = await waitFor(() => autoCap.got.slice(before).find((x) => x.path.includes(subPath)), 8000);
    if (!g) {
      if (i === 0) continue;   // 첫 줄은 [조회] 때 이미 받았을 수 있음
      throw new Error(`${i + 1}번째 사원 응답이 오지 않음`);
    }
    await sleep(300);
    g.cd_emp = panelEmpCode();
    g.row = i;
  }
  // 첫 줄(조회 때 받은 것)에도 사원코드를 붙인다
  const first = autoCap.got.find((x) => x.path.includes(subPath) && x.cd_emp === undefined);
  if (first) first.cd_emp = list.data[0].cd_emp;
}

// 화면 하나 받기: 같은 탭 안에서 화면 주소(#/smarta/모듈/코드)만 바꾸고, [조회]를 눌러 그 화면 코드의 응답을 모은다.
// onOpen: 화면을 열기만 해도 자료가 오는 화면(사원등록) — [조회]를 누르지 않는다.
async function runScreen(msg) {
  autoCap = {code: msg.code, got: []};
  window.postMessage({__ceoArm: 1, ms: msg.ms * 2 + 15000}, location.origin);
  const want = `#/smarta/${msg.mod}/${msg.code}`;
  if (!location.hash.startsWith(want + "?")) {
    const q = location.hash.slice(location.hash.indexOf("?"));
    location.hash = want + q;
    await sleep(3500);
  }
  // 해가 다른 화면이면 받지 않는다 (인사 화면은 탭을 처음 열 때의 해를 씀): 제목 '연말정산현황(2025)' 의 해와 맞춰 본다
  const ty = (document.title.match(/\((\d{4})\)/) || [])[1];
  if (msg.year && msg.mod === "humanresource" && ty && +ty !== +msg.year) { autoCap = null; return {ok: false, error: `화면 해가 ${ty}년이라 ${msg.year}년 자료를 못 받음`, got: [], v: BRIDGE_VERSION}; }
  let clicked = false;
  if (msg.tab) {   // 조회 조건을 스스로 채우는 탭을 누른다 (연말정산현황 '계속근무자')
    const t = await waitFor(() => [...document.querySelectorAll("button, a")].find((e) =>   // 탭 줄(li)이 아니라 단추를 눌러야 조회됨
      e.getBoundingClientRect().width > 0 && (e.innerText || "").trim() === msg.tab), 8000);
    if (t) { t.click(); clicked = true; }
  } else if (msg.fill === "earners") {
    await fillEarners();
    const b = await waitFor(findQueryButton, 3000);
    if (b) { b.click(); clicked = true; }
  } else if (msg.fill === "rows") {
    const b = await waitFor(findQueryButton, 8000);
    if (b) { b.click(); clicked = true; }
    await walkEmployeeRows(msg.sub || "/income/");
  } else if (!msg.onOpen) {
    const b = await waitFor(findQueryButton, 8000);
    if (b) { b.click(); clicked = true; }
  }
  let dialog = "";
  const t0 = Date.now();
  while (Date.now() - t0 < msg.ms && !autoCap.got.length) {
    dialog = clickLoadDialog() || dialog;
    await sleep(300);
  }
  // 첫 응답 뒤 딸린 응답(본표·목록·합계)까지: 새 응답이 2초 동안 없을 때까지 더 받는다 (길어도 ms 더)
  for (let n = -1, quiet = 0, t1 = Date.now(); autoCap.got.length && quiet < 2000 && Date.now() - t1 < msg.ms; ) {
    dialog = clickLoadDialog() || dialog;
    await sleep(250);
    if (autoCap.got.length !== n) { n = autoCap.got.length; quiet = 0; } else quiet += 250;
  }
  const got = autoCap.got; autoCap = null;
  return {ok: got.length > 0, clicked, dialog, screen: (document.title || "").split(" - ")[0], code: screenCode(), got, v: BRIDGE_VERSION};
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === "runScreen") {
    runScreen(msg).then(reply, (e) => { autoCap = null; reply({ok: false, error: String(e.message || e), got: [], v: BRIDGE_VERSION}); });
    return true;
  }
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
    reply({ok: !!b, screen: (document.title || "").split(" - ")[0], code: screenCode(), v: BRIDGE_VERSION});
  }
  if (msg && msg.type === "collectPlan") {
    collectPlan(msg.months).catch((e) => chrome.runtime.sendMessage({type: "planResult", rows: [], done: [], errors: [String(e.message || e)]}));
    reply({ok: true, v: BRIDGE_VERSION});
  }
});
