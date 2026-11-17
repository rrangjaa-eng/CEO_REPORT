// 확장 background.js 를 가짜 chrome 으로 띄워 '프로그램이 연 받기 주소' 처리를 본다 (2026-11-17). 결과는 JSON 한 줄.
const fs = require("fs"), vm = require("vm"), path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "..", "chrome_extension", "background.js"), "utf8");
const scenario = process.argv[2];
const log = {removed: [], created: [], marks: [], collectAll: 0};
const L = (o) => ({listeners: [], addListener(f) { this.listeners.push(f); }, removeListener() {}});
const ev = {onCreated: L(), onUpdated: L(), onMessage: L(), onInstalled: L()};
let smarta = scenario === "nosmarta" ? [] : [{id: 7, url: "https://smarta.wehago.com/#/smarta/account/SABK0113?cno=1&gisu=2&yminsa=2026"}];
const chrome = {
  runtime: {onMessage: ev.onMessage, onInstalled: ev.onInstalled, getURL: (x) => "chrome-extension://x/" + x},
  tabs: {onCreated: ev.onCreated, onUpdated: ev.onUpdated,
         remove: async (id) => { log.removed.push(id); },
         create: async (o) => { log.created.push(o.url); return {id: 99}; },
         query: async (q) => q.url ? smarta : [{id: 1}], sendMessage: async () => null, update: async () => {}},
  storage: {local: {get: async () => ({}), set: async () => {}}},
  action: {setBadgeText() {}}, downloads: {download: async () => {}, search: async () => []}, windows: {create: async () => {}, update: async () => {}},
};
const ctx = {chrome, console, setTimeout, clearTimeout, URL, TextEncoder, crypto: globalThis.crypto, btoa, Date,
  importScripts() {}, writeToFolder: async (name, text) => { if (name === "받기상태.txt") log.marks.push(JSON.parse(text)); return "ok"; }};
vm.createContext(ctx);
vm.runInContext(src, ctx);
vm.runInContext("collectAll = async (m) => { __hit(m); return {parts: {}}; }", Object.assign(ctx, {__hit: (m) => { log.collectAll++; log.months = m; }}));
const T = "https://smarta.wehago.com/ceo-report-collect";
const fire = (name, ...a) => ev[name].listeners.forEach((f) => f(...a));
(async () => {
  if (scenario === "content" || scenario === "content_opener" || scenario === "content_old") {   // 탭 알림 없이 쪽의 스크립트만 알림
    vm.runInContext("const __n = Date.now; Date.now = () => __n() + 60000", ctx);
    const tab = {id: 9, url: T}; if (scenario === "content_opener") tab.openerTabId = 2;
    fire("onMessage", {type: "programTrigger", fresh: scenario !== "content_old"}, {tab}, () => {});
  } else if (scenario === "opener") fire("onCreated", {id: 5, openerTabId: 3, pendingUrl: T});
  else if (scenario === "existing") {   // 확장이 깨어난 지 한참 뒤, 예전부터 있던 탭이 그 주소로 바뀜
    vm.runInContext("Date.now = () => startedAt + 60000", ctx);
    fire("onUpdated", 8, {url: T}, {id: 8, url: T});
  } else {
    if (scenario === "late") vm.runInContext("const __n = Date.now; Date.now = () => __n() + 60000", ctx);   // 확장이 깨어난 지 1분 뒤 누름
    fire("onCreated", {id: 5, pendingUrl: T});
    fire("onUpdated", 5, {url: T}, {id: 5, url: T});
    if (scenario === "double") fire("onCreated", {id: 6, pendingUrl: T});
  }
  await new Promise((r) => setTimeout(r, 50));
  console.log(JSON.stringify(log));
})();
