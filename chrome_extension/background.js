// 대표보고 위하고 수집 — 배경. 화면에서 받은 분개장을 다운로드 폴더 '위하고자동수집'에 JSON 으로 저장한다.
// 자동(30분)일 때는 지난번과 내용이 같으면 저장하지 않는다. 위하고에는 화면 [조회]만 누른다 (읽기 전용).
const FOLDER = "위하고자동수집";
const PERIOD_MIN = 30;
const SCREEN = {"분개장": "SABK0113"};
let pending = null;   // {kind, tabId, auto, resolve, timer}

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

async function save(msg, auto) {
  const s = stamp();
  // 내용 비교는 줄 자료만 (수집 시각 제외)
  const body = JSON.stringify(msg.rows);
  const hash = await sha(JSON.stringify(msg.params) + body);
  const key = "last_" + msg.kind;
  const prev = (await chrome.storage.local.get(key))[key];
  if (auto && prev && prev.hash === hash) {
    await setStatus({[msg.kind]: Object.assign({}, prev, {checked: s.iso, changed: false})});
    return {saved: false, same: true};
  }
  const file = {"종류": msg.kind, "형식": 1, "수집시각": s.iso, "회사": msg.company, "기간": msg.params,
                "전표수": msg.tot, "줄수": msg.rows.length, "열": msg.columns, "줄": msg.rows};
  const name = `${FOLDER}/${s.ymd6} ${msg.kind} 자동수집.json`;
  await chrome.downloads.download({url: toDataUrl(JSON.stringify(file)), filename: name, conflictAction: "overwrite", saveAs: false});
  const info = {hash, saved: s.iso, checked: s.iso, rows: msg.rows.length, slips: msg.tot, file: name, changed: !!prev};
  await chrome.storage.local.set({[key]: info});
  await setStatus({[msg.kind]: info, error: ""});
  return {saved: true, file: name};
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === "captured") {
    const auto = !!(pending && pending.tabId === sender.tab.id && pending.auto);
    save(msg, auto).then((r) => {
      if (pending && pending.tabId === sender.tab.id && pending.kind === msg.kind) {
        clearTimeout(pending.timer);
        const p = pending; pending = null;
        p.resolve(r);
      }
    });
    return false;
  }
  if (msg && msg.type === "collectNow") {
    collect("분개장", false).then(reply, (e) => reply({error: String(e.message || e)}));
    return true;
  }
  if (msg && msg.type === "setAuto") {
    setAuto(msg.on).then(() => reply({ok: true}));
    return true;
  }
});

async function findSmartaTab() {
  const tabs = await chrome.tabs.query({url: "https://smarta.wehago.com/*"});
  return tabs.find((t) => /[?&]cno=/.test(t.url) || /cNum=/.test(t.url)) || null;
}

function screenUrl(fromUrl, screen) {
  // 열린 SmartA 탭 주소의 회사 값(cno·cd_com·gisu…)을 그대로 쓰고 화면 번호만 바꾼다
  const u = new URL(fromUrl);
  const m = u.hash.match(/^#\/smarta\/account\/[A-Z0-9]+(\?.*)$/);
  if (m) return `${u.origin}/#/smarta/account/${screen}${m[1]}`;
  return null;
}

function waitLoaded(tabId, ms) {
  return new Promise((resolve) => {
    const t = setTimeout(done, ms);
    function done() { clearTimeout(t); chrome.tabs.onUpdated.removeListener(on); resolve(); }
    function on(id, info) { if (id === tabId && info.status === "complete") setTimeout(done, 4000); }
    chrome.tabs.onUpdated.addListener(on);
  });
}

async function collect(kind, auto) {
  if (pending) return {error: "이미 수집 중입니다"};
  const src = await findSmartaTab();
  if (!src) {
    await setStatus({error: "위하고 SmartA 화면이 열려 있지 않음", badge: "!"});
    return {error: "위하고에 로그인한 뒤 SmartA(회계) 화면을 한 번 열어 두세요."};
  }
  const url = screenUrl(src.url, SCREEN[kind]);
  if (!url) return {error: "SmartA 회계 화면(분개장·자금계획서 등)을 한 번 열어 두세요."};
  const tab = await chrome.tabs.create({url, active: false});
  await waitLoaded(tab.id, 30000);
  const result = await new Promise(async (resolve) => {
    pending = {kind, tabId: tab.id, auto, resolve, timer: setTimeout(() => { pending = null; resolve({error: "응답이 오지 않음 (로그인이 풀렸을 수 있음)"}); }, 120000)};
    try {
      const r = await chrome.tabs.sendMessage(tab.id, {type: "clickQuery"});
      if (!r || !r.ok) { clearTimeout(pending.timer); pending = null; resolve({error: "[조회] 버튼을 찾지 못함 (로그인이 풀렸을 수 있음)"}); }
    } catch (e) { clearTimeout(pending.timer); pending = null; resolve({error: "화면과 연결하지 못함"}); }
  });
  try { await chrome.tabs.remove(tab.id); } catch (e) { /* 이미 닫힘 */ }
  if (result.error) await setStatus({error: result.error, badge: "!"});
  return result;
}

async function setAuto(on) {
  await chrome.storage.local.set({auto: !!on});
  if (on) chrome.alarms.create("collect", {periodInMinutes: PERIOD_MIN, delayInMinutes: 1});
  else chrome.alarms.clear("collect");
}

chrome.alarms.onAlarm.addListener((a) => { if (a.name === "collect") collect("분개장", true); });
chrome.runtime.onInstalled.addListener(async () => {
  const {auto} = await chrome.storage.local.get("auto");
  if (auto) setAuto(true);
});
