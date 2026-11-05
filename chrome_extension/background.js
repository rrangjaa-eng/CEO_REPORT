// 대표보고 위하고 수집 — 배경. 화면에서 받은 분개장·자금계획을 다운로드 폴더 '위하고자동수집'에 JSON 으로 저장한다.
// 사용자가 단추를 누를 때만 받는다 (2026-11-05: 30분 자동 확인 없음). 지난번과 내용이 같으면 새로 저장하지 않는다.
// 위하고에는 날짜 고르기·[조회]·줄 고르기만 한다 (읽기 전용).
const FOLDER = "위하고자동수집";
const SCREEN = {"분개장": "SABK0113", "자금계획": "SAFM0102"};
const PLAN_COLUMNS = ["date", "yn_inout", "cd_fitem", "nm_fitem", "cd_trade", "nm_trade", "mn_fplan", "rmk_fplan", "str_refer", "da_fplan"];
let pending = null;   // 분개장: {kind, tabId, resolve, timer}
let planRun = null;   // 자금계획: {tabId, resolve, timer}

const pad = (n) => String(n).padStart(2, "0");
function stamp(d = new Date()) {
  return {ymd6: String(d.getFullYear()).slice(2) + pad(d.getMonth() + 1) + pad(d.getDate()),
          iso: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`};
}

async function sha(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function toDataUrl(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return "data:application/json;base64," + btoa(bin);
}

async function setStatus(patch) {
  const {status = {}} = await chrome.storage.local.get("status");
  Object.assign(status, patch);
  await chrome.storage.local.set({status});
  chrome.action.setBadgeText({text: patch.badge || ""});
}

// 내용(hashSource)이 지난번과 같으면 저장하지 않는다.
async function saveFile(kind, file, hashSource, summary) {
  const s = stamp();
  const hash = await sha(hashSource);
  const key = "last_" + kind;
  const prev = (await chrome.storage.local.get(key))[key];
  if (prev && prev.hash === hash) {
    const info = Object.assign({}, prev, {checked: s.iso, changed: false});
    await chrome.storage.local.set({[key]: info});
    await setStatus({[kind]: info, error: ""});
    return {saved: false, same: true};
  }
  file["수집시각"] = s.iso;
  const name = `${FOLDER}/${s.ymd6} ${kind} 자동수집.json`;
  await chrome.downloads.download({url: toDataUrl(JSON.stringify(file)), filename: name, conflictAction: "overwrite", saveAs: false});
  const info = Object.assign({hash, saved: s.iso, checked: s.iso, file: name, changed: !!prev}, summary);
  await chrome.storage.local.set({[key]: info});
  await setStatus({[kind]: info, error: ""});
  return {saved: true, file: name};
}

async function saveJournal(msg) {
  const file = {"종류": msg.kind, "형식": 1, "수집시각": "", "회사": msg.company, "기간": msg.params,
                "전표수": msg.tot, "줄수": msg.rows.length, "열": msg.columns, "줄": msg.rows};
  return saveFile(msg.kind, file, JSON.stringify(msg.params) + JSON.stringify(msg.rows), {rows: msg.rows.length, slips: msg.tot});
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg) return;
  if (msg.type === "captured") {
    if (!(pending && sender.tab && pending.tabId === sender.tab.id)) return;   // 사용자가 화면에서 직접 [조회]한 것은 저장하지 않음
    saveJournal(msg).then((r) => {
      if (pending && pending.tabId === sender.tab.id && pending.kind === msg.kind) {
        clearTimeout(pending.timer);
        const p = pending; pending = null;
        p.resolve(r);
      }
    });
    return;
  }
  if (msg.type === "planProgress" || msg.type === "planResult") {
    if (!(planRun && sender.tab && planRun.tabId === sender.tab.id)) return;
    clearTimeout(planRun.timer);
    if (msg.type === "planProgress") {
      planRun.timer = setTimeout(planRun.fail, 90000);
      setStatus({progress: `자금계획 ${msg.date} 까지 받음 (${msg.rows}줄)`});
    } else {
      const p = planRun; planRun = null;
      p.resolve(msg);
    }
    return;
  }
  if (msg.type === "collectNow") {
    collectJournal().then(reply, (e) => reply({error: String(e.message || e)}));
    return true;
  }
  if (msg.type === "collectAll") {
    collectAll(msg.months).then(reply, (e) => reply({error: String(e.message || e)}));
    return true;
  }
  if (msg.type === "collectPlan") {
    collectPlan(msg.months).then(reply, (e) => reply({error: String(e.message || e)}));
    return true;
  }
});

async function findSmartaTab() {
  const tabs = await chrome.tabs.query({url: "https://smarta.wehago.com/*"});
  return tabs.find((t) => /[?&]cno=/.test(t.url)) || null;
}

// 자금계획은 searchDate 없이 열어야 '0. 계획월' 보기(달 단위 조회)로 열린다.
// 열린 SmartA 탭 주소의 회사 값(cno·cd_com…)을 그대로 쓰고 화면 번호(그리고 필요하면 기수·연도)만 바꾼다.
function screenUrl(fromUrl, screen, year) {
  const u = new URL(fromUrl);
  const m = u.hash.match(/^#\/smarta\/account\/[A-Z0-9]+(\?.*)$/);
  if (!m) return null;
  let q = m[1];
  if (year) {
    const gisu = +(q.match(/[?&]gisu=(\d+)/) || [])[1];
    const base = +(q.match(/[?&]yminsa=(\d{4})/) || [])[1];
    if (!gisu || !base) return null;
    q = q.replace(/([?&]gisu=)\d+/, "$1" + (gisu + year - base))   // 회계연도 = 달력 연도 (1기 2025, 2기 2026, 3기 2027)
         .replace(/([?&]yminsa=)\d{4}/, "$1" + year)
         .replace(/([?&]searchData=)\d+/, `$1${year}0101${year}1231`)
         .replace(/[?&]searchDate=\d+/, "");
  }
  return `${u.origin}/#/smarta/account/${screen}${q}`;
}

function waitLoaded(tabId, ms) {
  return new Promise((resolve) => {
    const t = setTimeout(done, ms);
    function done() { clearTimeout(t); chrome.tabs.onUpdated.removeListener(on); resolve(); }
    function on(id, info) { if (id === tabId && info.status === "complete") setTimeout(done, 4000); }
    chrome.tabs.onUpdated.addListener(on);
  });
}

async function sourceTab() {
  const src = await findSmartaTab();
  if (!src) {
    await setStatus({error: "위하고 SmartA 화면이 열려 있지 않음", badge: "!"});
    throw new Error("위하고에 로그인한 뒤 SmartA(회계) 화면을 한 번 열어 두세요.");
  }
  return src;
}

async function collectJournal() {
  if (pending || planRun) return {error: "이미 받는 중입니다"};
  const src = await sourceTab();
  const url = screenUrl(src.url, SCREEN["분개장"]);
  if (!url) return {error: "SmartA 회계 화면(분개장·자금계획서 등)을 한 번 열어 두세요."};
  const tab = await chrome.tabs.create({url, active: false});
  await waitLoaded(tab.id, 30000);
  const result = await new Promise(async (resolve) => {
    pending = {kind: "분개장", tabId: tab.id, resolve, timer: setTimeout(() => { pending = null; resolve({error: "응답이 오지 않음 (로그인이 풀렸을 수 있음)"}); }, 120000)};
    try {
      const r = await chrome.tabs.sendMessage(tab.id, {type: "clickQuery"});
      if (!r || !r.ok) { clearTimeout(pending.timer); pending = null; resolve({error: "[조회] 버튼을 찾지 못함 (로그인이 풀렸을 수 있음)"}); }
    } catch (e) { clearTimeout(pending.timer); pending = null; resolve({error: "화면과 연결하지 못함"}); }
  });
  try { await chrome.tabs.remove(tab.id); } catch (e) { /* 이미 닫힘 */ }
  if (result.error) await setStatus({error: result.error, badge: "!"});
  return result;
}

// 이번 달부터 months 개월 (연도별로 나눔: 기수가 연도마다 다름) -> {2026: ["202611", "202612"], 2027: ["202701"]}
function planMonths(months, today = new Date()) {
  const byYear = {};
  for (let i = 0; i < months; i++) {
    const d = new Date(today.getFullYear(), today.getMonth() + i, 1);
    const y = d.getFullYear();
    (byYear[y] = byYear[y] || []).push(`${y}${pad(d.getMonth() + 1)}`);
  }
  return byYear;
}

async function runPlanTab(url, months) {
  // 자금항목 표(RealGrid)는 숨은 탭에서는 그리지 않아 줄 클릭이 안 먹는다 (2026-11-05 실제 PC):
  // 받는 동안만 탭을 앞에 띄우고, 끝나면 원래 보던 탭으로 돌아간다.
  const [prev] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  const tab = await chrome.tabs.create({url, active: true, windowId: prev ? prev.windowId : undefined});
  await waitLoaded(tab.id, 30000);
  const result = await new Promise(async (resolve) => {
    const fail = () => { planRun = null; resolve({error: "응답이 멈춤", rows: [], done: [], errors: ["90초 동안 화면 응답 없음 (로그인이 풀렸거나 확장 새로고침이 필요할 수 있음)"]}); };
    planRun = {tabId: tab.id, resolve, fail, timer: setTimeout(fail, 90000)};
    try {
      const ack = await chrome.tabs.sendMessage(tab.id, {type: "collectPlan", months});
      if (!ack || (ack.v || 0) < 4) {
        clearTimeout(planRun.timer); planRun = null;
        resolve({error: "확장 파일이 예전 것임 — chrome://extensions 에서 이 확장의 새로고침(↻)을 누르고 위하고 탭도 새로고침하세요", rows: [], done: [], errors: ["확장 새로고침 필요"]});
      }
    } catch (e) { clearTimeout(planRun.timer); planRun = null; resolve({error: "화면과 연결하지 못함", rows: [], done: [], errors: ["화면과 연결하지 못함"]}); }
  });
  try { await chrome.tabs.remove(tab.id); } catch (e) { /* 이미 닫힘 */ }
  if (prev) { try { await chrome.tabs.update(prev.id, {active: true}); } catch (e) { /* 닫힘 */ } }
  return result;
}

async function collectPlan(months) {
  if (pending || planRun) return {error: "이미 받는 중입니다"};
  months = Math.max(1, Math.min(12, +months || 3));
  await chrome.storage.local.set({planMonths: months});
  const src = await sourceTab();
  const byYear = planMonths(months);
  const rows = [], done = [], errors = [];
  let company = "";
  const t0 = Date.now();
  for (const year of Object.keys(byYear).sort()) {
    const url = screenUrl(src.url, SCREEN["자금계획"], +year);
    if (!url) { errors.push("SmartA 회계 화면 주소에서 기수를 찾지 못함"); break; }
    const r = await runPlanTab(url, byYear[year]);
    rows.push(...r.rows); done.push(...r.done); errors.push(...r.errors);
    company = company || r.company || "";
    if (r.errors.length) break;
  }
  const all = Object.values(byYear).flat();
  const file = {"종류": "자금계획", "형식": 1, "수집시각": "", "회사": company,
                "기간": {"from": all[0], "to": all[all.length - 1], "months": months},
                "조회한달": done, "오류": errors, "줄수": rows.length, "열": PLAN_COLUMNS, "줄": rows};
  await setStatus({progress: ""});
  if (!done.length) {
    await setStatus({error: errors[0] || "받은 달이 없음", badge: "!"});
    return {error: errors[0] || "받은 달이 없음"};
  }
  const r = await saveFile("자금계획", file, JSON.stringify([file["기간"], done, errors, rows]),
                           {rows: rows.length, months: done.length, seconds: Math.round((Date.now() - t0) / 1000), errors: errors.length});
  if (errors.length) {
    await setStatus({error: `${done[done.length - 1] || ""} 까지만 받음 — ${errors[0]}`, badge: "!"});
    r.error = `일부만 받음: ${errors[0]}`;
  }
  return r;
}

// 모두 받기: 분개장 → 자금계획 차례로 (하나가 실패해도 다음 것은 받는다)
async function collectAll(months) {
  const out = {};
  for (const [kind, fn] of [["분개장", () => collectJournal()], ["자금계획", () => collectPlan(months)]]) {
    try { out[kind] = await fn(); } catch (e) { out[kind] = {error: String(e.message || e)}; }
  }
  const errs = Object.entries(out).filter(([k, r]) => r && r.error).map(([k, r]) => `${k}: ${r.error}`);
  return errs.length ? {error: errs.join(" / "), parts: out} : {parts: out};
}

chrome.runtime.onInstalled.addListener(() => { chrome.alarms && chrome.alarms.clearAll(); });
