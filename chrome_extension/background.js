// 대표보고 위하고 수집 — 배경. 화면에서 받은 분개장·자금계획을 다운로드 폴더 '위하고자동수집'에 JSON 으로 저장한다.
// 사용자가 단추를 누를 때만 받는다 (2026-11-05: 30분 자동 확인 없음). 지난번과 내용이 같으면 새로 저장하지 않는다.
// 위하고에는 날짜 고르기·[조회]·줄 고르기만 한다 (읽기 전용).
importScripts("folder.js");
const FOLDER = "위하고자동수집";   // 저장 폴더를 아직 고르지 않았을 때만 쓰는 크롬 다운로드 폴더 안 폴더
const SCREEN = {"분개장": "SABK0113", "자금계획": "SAFM0102"};
const PLAN_COLUMNS = ["date", "yn_inout", "cd_fitem", "nm_fitem", "cd_trade", "nm_trade", "mn_fplan", "rmk_fplan", "str_refer", "da_fplan"];
let pending = null;   // 분개장: {kind, tabId, resolve, timer}
let planRun = null;   // 자금계획: {tabId, resolve, timer}
let closingRun = null;   // 결산 자료: {tabId, got: [{path, data}], screen, code}

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

async function openSaver() {
  const url = chrome.runtime.getURL("saver.html");
  const tabs = await chrome.tabs.query({url: url + "*"});
  if (tabs.length) { await chrome.windows.update(tabs[0].windowId, {focused: true}); await chrome.tabs.reload(tabs[0].id); return; }
  await chrome.windows.create({url: url + "?auto=1", type: "popup", width: 560, height: 320, focused: true});
}

// 고른 저장 폴더(수집\위하고)에 바로 쓴다. 허용이 다시 필요하면 저장 창을 띄워 기다리게 두고, 폴더를 아직 안 골랐으면 다운로드 폴더에 둔다.
async function writeOut(fname, text) {
  const r = await writeToFolder(fname, text);
  if (r === "ok") return "위하고 폴더";
  if (r === "need") {
    const {pendingSaves = []} = await chrome.storage.local.get("pendingSaves");
    const rest = pendingSaves.filter((p) => p.name !== fname);
    rest.push({name: fname, text});
    await chrome.storage.local.set({pendingSaves: rest});
    await openSaver();
    return "허용 기다림";
  }
  await chrome.downloads.download({url: toDataUrl(text), filename: `${FOLDER}/${fname}`, conflictAction: "overwrite", saveAs: false});
  return "다운로드 폴더 (저장 폴더를 아직 고르지 않음)";
}

// 내용(hashSource)이 지난번과 같고 이미 저장 폴더에 들어가 있으면 저장하지 않는다.
async function saveFile(kind, file, hashSource, summary) {
  const s = stamp();
  const hash = await sha(hashSource);
  const key = "last_" + kind;
  const prev = (await chrome.storage.local.get(key))[key];
  // 같은 내용이라도 지금 저장 폴더에 아직 안 들어갔으면(예전 다운로드 폴더 저장·허용 기다림) 다시 저장한다
  const dir = await getFolder();
  const placed = prev && (dir ? prev.where === "위하고 폴더" : !!prev.where && prev.where !== "허용 기다림");
  if (prev && prev.hash === hash && placed) {
    const info = Object.assign({}, prev, {checked: s.iso, changed: false});
    await chrome.storage.local.set({[key]: info});
    await setStatus({[kind]: info, error: ""});
    return {saved: false, same: true};
  }
  file["수집시각"] = s.iso;
  const fname = `${s.ymd6} ${kind} 자동수집.json`;
  const where = await writeOut(fname, JSON.stringify(file));
  const info = Object.assign({hash, saved: s.iso, checked: s.iso, file: fname, where, changed: !!prev}, summary);
  await chrome.storage.local.set({[key]: info});
  await setStatus({[kind]: info, error: ""});
  return {saved: true, file: fname, where};
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
  if (msg.type === "folderSaved") {
    (async () => {
      const {status = {}} = await chrome.storage.local.get("status");
      for (const kind of ["분개장", "자금계획"]) {
        const key = "last_" + kind;
        const info = (await chrome.storage.local.get(key))[key];
        if (info && msg.names.includes(info.file)) {
          info.where = "위하고 폴더";
          await chrome.storage.local.set({[key]: info});
          status[kind] = info;
        }
      }
      await chrome.storage.local.set({status});
    })();
    return;
  }
  if (msg.type === "closingCaptured") {
    if (closingRun && sender.tab && closingRun.tabId === sender.tab.id) closingRun.got.push({path: msg.path, data: msg.data});
    return;
  }
  if (msg.type === "collectClosing" || msg.type === "collectHr" || msg.type === "collectYearEnd") {
    const prefix = {collectHr: "인사", collectYearEnd: "연말정산"}[msg.type] || "결산";
    collectClosing(prefix).then(reply, (e) => reply({error: String(e.message || e)}));
    return true;
  }
  if (msg.type === "collectBooks") {
    collectBooks().then(reply, (e) => reply({error: String(e.message || e)}));
    return true;
  }
  if (msg.type === "openSaver") { openSaver(); return; }
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
function screenUrl(fromUrl, screen, year, mod = "account") {
  const u = new URL(fromUrl);
  const m = u.hash.match(/^#\/smarta\/(?:account|humanresource)\/[A-Z0-9]+(\?.*)$/);
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
  return `${u.origin}/#/smarta/${mod}/${screen}${q}`;
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

// 지난달 + 이번 달부터 months 개월 (연도별로 나눔: 기수가 연도마다 다름) -> {2026: ["202610", "202611", "202612"], 2027: ["202701"]}
// 지난달: 예정일이 지났는데 아직 나가거나 들어오지 않은 돈(지난 미지급·미수)도 받는다 (사용자 2026-11-12)
const PAST_MONTHS = 1;
function planMonths(months, today = new Date()) {
  const byYear = {};
  for (let i = -PAST_MONTHS; i < months; i++) {
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

// 결산 자료 받기 (사용자 2026-11-12): 위하고에서 지금 열려 있는 결산 화면(재무상태표·이익잉여금처분계산서·고정자산 등)에서
// [조회]를 한 번 누르고 15초 동안 온 응답을 원본 그대로 'YYMMDD 결산_<화면이름> 자동수집.json' 으로 저장한다.
// 화면마다 위하고 내부 주소를 확인한 뒤에는 단추 하나로 세 화면을 차례로 받게 바꾼다. 위하고에서는 [조회]만 누른다 (읽기 전용).
const CLOSING_MS = 15000;
// 인사·급여 자료 받기 (사용자 2026-11-12): 같은 방식으로 사원등록·급여자료입력·사업소득·기타소득 화면 응답을 'YYMMDD 인사_<화면이름>' 으로 저장.
// 연말정산 결과 받기 (사용자 2026-11-12): 같은 방식으로 'YYMMDD 연말정산_<화면이름>' 으로 저장. 직원별 인적공제(부양가족·자녀 수)와
// 공제 항목을 다음 해 연말정산 예상·매달 원천세(간이세액표 공제대상가족 수)에 쓴다.
// 직원 개인정보: 원본은 사용자 PC 저장 폴더에만 두고, 프로그램은 생년월일·입퇴사일·급여 항목만 읽는다 (주민번호 뒷자리는 쓰지 않음).
async function collectClosing(prefix = "결산") {
  if (pending || planRun || closingRun || booksRun) return {error: "이미 받는 중입니다"};
  const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  if (!tab || !/^https:\/\/smarta\.wehago\.com\//.test(tab.url || "")) {
    return {error: {"인사": "위하고 SmartA 에서 사원등록·급여자료입력·사업소득·기타소득 화면 중 하나를 열고, 조회 조건을 고른 뒤 이 단추를 누르세요.",
                    "연말정산": "위하고 SmartA 에서 연말정산 결과 화면(연말정산자료입력 또는 근로소득 원천징수영수증)을 열고, 2025년 귀속·사원을 고른 뒤 이 단추를 누르세요."}[prefix]
                   || "위하고 SmartA 에서 받을 결산 화면(재무상태표 등)을 열고, 연도를 고른 뒤 이 단추를 누르세요."};
  }
  closingRun = {tabId: tab.id, got: []};
  let ack;
  try { ack = await chrome.tabs.sendMessage(tab.id, {type: "armClosing", ms: CLOSING_MS}); } catch (e) { ack = null; }
  if (!ack || (ack.v || 0) < 5) {
    closingRun = null;
    return {error: "확장 파일이 예전 것임 — chrome://extensions 에서 이 확장의 새로고침(↻)을 누르고 위하고 탭도 새로고침하세요"};
  }
  if (!ack.ok) { closingRun = null; return {error: "이 화면에서 [조회] 버튼을 찾지 못함"}; }
  await new Promise((r) => setTimeout(r, CLOSING_MS));
  const run = closingRun; closingRun = null;
  if (!run.got.length) return {error: `${ack.screen || "이 화면"}: 응답이 오지 않음 (조회 조건을 고른 뒤 다시 눌러 보세요)`};
  const name = (ack.screen || ack.code || "화면").replace(/[\\/:*?"<>|\s]+/g, "");
  const file = {"종류": prefix + "원본", "형식": 1, "수집시각": "", "화면": ack.screen, "화면코드": ack.code, "응답수": run.got.length, "응답": run.got};
  const r = await saveFile(prefix + "_" + name, file, JSON.stringify(run.got), {rows: run.got.length, screen: ack.screen});
  const logKey = {"인사": "hrLog", "연말정산": "yearEndLog"}[prefix] || "closingLog";
  const log = (await chrome.storage.local.get(logKey))[logKey] || [];
  const s = stamp();
  log.unshift({at: s.iso, screen: ack.screen, code: ack.code, file: r.file || "(바뀐 것 없음)", where: r.where || ""});
  await chrome.storage.local.set({[logKey]: log.slice(0, 8)});
  return Object.assign(r, {screen: ack.screen});
}

// 결산·인사급여 모두 받기 (사용자 2026-11-13: 화면마다 열고 [조회] 누르는 손일을 없앰).
// 위하고 화면을 한 탭에 띄워 아래 화면을 차례로 열고 [조회]를 누른 뒤, 그 화면의 응답만 'YYMMDD 결산_재무상태표 자동수집.json' 처럼 저장한다.
// 결산은 올해와 작년(결산 끝난 해) 두 해, 인사·급여는 올해. 위하고에서는 화면 열기·[조회]·'불러오시겠습니까' [확인]만 한다 (읽기 전용).
// 연말정산현황은 작년 해 탭에서 '계속근무자' 쪽을 눌러 받는다. 사업/기타소득조회는 달을 골라도 위하고가 '조회조건 누락'을 띄워 아직 못 받는다.
const AUTO_SCREENS = [
  {prefix: "결산", mod: "account", code: "SACL0105", name: "재무상태표", years: [0, -1]},
  {prefix: "결산", mod: "account", code: "SACL0108", name: "이익잉여금처분계산서", years: [0, -1]},
  {prefix: "결산", mod: "account", code: "SAAS0107", name: "고정자산관리대장", years: [0]},
  {prefix: "인사", mod: "humanresource", code: "SWPM0108", name: "사원등록", years: [0], onOpen: true},
  {prefix: "인사", mod: "humanresource", code: "SWSA0105", name: "월별급상여수당지급현황", years: [0, -1]},
  // 연말정산현황: 작년 해로 열면 '계속근무자' 쪽이 정산년월(작년 1월~올해 2월)을 스스로 채워 조회한다 (2026-11-13 실제 화면 확인)
  {prefix: "연말정산", mod: "humanresource", code: "SWYM0102", name: "연말정산현황", years: [-1], tab: "계속근무자 연말정산현황"},
];
const SCREEN_MS = 15000;
let booksRun = false;

async function collectBooks() {
  if (pending || planRun || closingRun || booksRun) return {error: "이미 받는 중입니다"};
  const src = await sourceTab();
  const base = +((new URL(src.url).hash.match(/[?&]yminsa=(\d{4})/) || [])[1]) || new Date().getFullYear();
  booksRun = true;
  const t0 = Date.now();
  const done = [], fails = [];
  const [prev] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  try {
    for (const dy of [0, -1]) {   // 해마다 탭 하나 (기수·연도는 주소로 처음 열 때만 바뀜)
      const year = base + dy;
      const list = AUTO_SCREENS.filter((x) => x.years.includes(dy));
      const first = list[0];
      const url = screenUrl(src.url, first.code, year, first.mod);
      if (!url) { fails.push(`${year}: SmartA 화면 주소에서 기수를 찾지 못함`); continue; }
      // 그림 표·안내 창은 숨은 탭에서 그리지 않을 수 있어 받는 동안만 앞에 띄운다 (자금계획과 같음)
      const tab = await chrome.tabs.create({url, active: true, windowId: prev ? prev.windowId : undefined});
      await waitLoaded(tab.id, 30000);
      for (const sc of list) {
        await setStatus({progress: `결산·인사급여: ${year} ${sc.name} 받는 중…`});
        let r;
        try { r = await chrome.tabs.sendMessage(tab.id, {type: "runScreen", mod: sc.mod, code: sc.code, onOpen: !!sc.onOpen, tab: sc.tab || "", year, ms: SCREEN_MS}); }
        catch (e) { r = null; }
        if (!r || (r.v || 0) < 6) {
          fails.push("확장 파일이 예전 것임 — chrome://extensions 에서 이 확장의 새로고침(↻)을 누르고 위하고 탭도 새로고침하세요");
          break;
        }
        if (!r.ok) { fails.push(`${year} ${sc.name}: 응답이 오지 않음` + (r.error ? ` (${r.error})` : (sc.onOpen || r.clicked ? "" : (sc.tab ? ` ('${sc.tab}' 못 찾음)` : " ([조회] 버튼 못 찾음)")))); continue; }
        const kind = `${sc.prefix}_${sc.name}` + (dy ? `_${year}` : "");
        const file = {"종류": sc.prefix + "원본", "형식": 1, "수집시각": "", "연도": year, "화면": sc.name, "화면코드": sc.code,
                      "자동": true, "응답수": r.got.length, "응답": r.got};
        const saved = await saveFile(kind, file, JSON.stringify(r.got), {rows: r.got.length, screen: sc.name});
        done.push({kind, file: saved.file || "(바뀐 것 없음)", same: !!saved.same});
      }
      try { await chrome.tabs.remove(tab.id); } catch (e) { /* 이미 닫힘 */ }
      if (fails.some((f) => f.startsWith("확장 파일"))) break;
    }
  } finally {
    booksRun = false;
    if (prev) { try { await chrome.tabs.update(prev.id, {active: true}); } catch (e) { /* 닫힘 */ } }
  }
  const s = stamp();
  const log = {at: s.iso, seconds: Math.round((Date.now() - t0) / 1000), done: done.map((d) => d.kind), same: done.filter((d) => d.same).length, fails};
  await chrome.storage.local.set({booksLog: log});
  await setStatus({progress: ""});
  const r = {done: done.length, same: done.filter((d) => d.same).length, files: done};
  if (fails.length) r.error = fails.join(" / ");
  return r;
}

chrome.runtime.onInstalled.addListener(() => { chrome.alarms && chrome.alarms.clearAll(); });
