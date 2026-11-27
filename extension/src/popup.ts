import {getFolder} from "./folder";
import type {CollectResult, PopupRequest} from "./messages";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const monthsSel = () => $<HTMLSelectElement>("months");
for (let i = 1; i <= 12; i++) monthsSel().add(new Option(String(i), String(i)));

interface Info { saved: string; checked?: string; where?: string; [k: string]: unknown }
interface LogItem { at: string; screen?: string; code?: string; file: string }
interface BooksLog { at: string; seconds: number; done: string[]; same: number; fails: string[] }

function line(info: Info | undefined, what: (i: Info) => string): string {
  if (!info) return "아직 받은 적 없음";
  let s = `마지막 저장: ${info.saved}<br>${what(info)}` + (info.where ? `<br>저장 위치: ${info.where}` : "");
  if (info.checked && info.checked !== info.saved) s += `<br>마지막 확인: ${info.checked} (바뀐 것 없음)`;
  return s;
}

async function show(): Promise<void> {
  try {
    const dir = await getFolder();
    const {pendingSaves = []} = (await chrome.storage.local.get("pendingSaves")) as {pendingSaves?: unknown[]};
    $("fmsg").innerHTML = (dir ? `저장 폴더: <b>${dir.name}</b>` : `<span class="err">저장 폴더를 아직 고르지 않았습니다 (지금은 다운로드 폴더에 저장)</span>`)
      + (pendingSaves.length ? `<br><span class="err">저장 허용 기다리는 파일 ${pendingSaves.length}개 — 아래 단추를 눌러 주세요</span>` : "");
  } catch (e) { $("fmsg").textContent = ""; }
  const {status = {}, planMonths = 3} = (await chrome.storage.local.get(["status", "planMonths"])) as {status?: Record<string, unknown>; planMonths?: number};
  monthsSel().value = String(planMonths);
  $("jmsg").innerHTML = line(status["분개장"] as Info | undefined, (j) => `전표 ${j.slips}건 · ${j.rows}줄`);
  $("pmsg").innerHTML = line(status["자금계획"] as Info | undefined, (p) => `${p.months}개월 · ${p.rows}줄 (${p.seconds}초)`);
  if (status.progress) $("pmsg").innerHTML += `<br>${status.progress}`;
  const {closingLog = []} = (await chrome.storage.local.get("closingLog")) as {closingLog?: LogItem[]};
  const {hrLog = []} = (await chrome.storage.local.get("hrLog")) as {hrLog?: LogItem[]};
  const {yearEndLog = []} = (await chrome.storage.local.get("yearEndLog")) as {yearEndLog?: LogItem[]};
  $("ymsg").innerHTML = yearEndLog.slice(0, 2).map((c) => `연말정산 ${c.at.slice(5, 16)} · ${c.screen || c.code} · ${c.file}`).join("<br>");
  $("hmsg").innerHTML = hrLog.slice(0, 2).map((c) => `인사·급여 ${c.at.slice(5, 16)} · ${c.screen || c.code} · ${c.file}`).join("<br>");
  $("cmsg").innerHTML = closingLog.slice(0, 2).map((c) => `결산 ${c.at.slice(5, 16)} · ${c.screen || c.code} · ${c.file}`).join("<br>");
  const {booksLog} = (await chrome.storage.local.get("booksLog")) as {booksLog?: BooksLog};
  $("bmsg").innerHTML = booksLog ? `마지막: ${booksLog.at.slice(5, 16)} · ${booksLog.done.length}개 화면 (${booksLog.seconds}초)` + (booksLog.same ? ` · ${booksLog.same}개는 바뀐 것 없음` : "")
    + (booksLog.fails.length ? `<br><span class="err">${booksLog.fails.join("<br>")}</span>` : "") : "아직 받은 적 없음";
  if (status.progress && /^결산·인사급여/.test(String(status.progress))) $("bmsg").innerHTML += `<br>${status.progress}`;
  if (status.error) $("pmsg").innerHTML += `<br><span class="err">${status.error}</span>`;
}

const BUTTONS = ["books", "all", "journal", "plan", "closing", "hr", "ye"];
async function run(_btn: string, msgId: string, label: string, message: PopupRequest): Promise<void> {
  for (const b of BUTTONS) $<HTMLButtonElement>(b).disabled = true;
  $(msgId).textContent = label;
  const timer = setInterval(show, 2000);
  const r = (await chrome.runtime.sendMessage(message)) as CollectResult | undefined;
  clearInterval(timer);
  for (const b of BUTTONS) $<HTMLButtonElement>(b).disabled = false;
  await show();
  if (r && r.parts) for (const [k, p] of Object.entries(r.parts)) if (p && p.same) $(msgId).innerHTML += `<br>${k}: 바뀐 것 없음`;
  if (r && r.same) $(msgId).innerHTML += "<br>바뀐 것 없음 — 새 파일 만들지 않음";
  if (r && r.error) $(msgId).innerHTML += `<br><span class="err">${r.error}</span>`;
}

const months = () => +monthsSel().value;
$("all").onclick = () => run("all", "amsg", "분개장 → 대조 화면(시산표·차입금 등) → 자금계획 차례로 받는 중… 위하고 화면이 잠깐 앞에 떴다 닫힙니다.", {type: "collectAll", months: months()});
$("books").onclick = () => run("books", "bmsg", "받는 중… 위하고 화면이 1~2분 앞에 떴다 닫힙니다. 끝날 때까지 다른 탭으로 옮기지 마세요.", {type: "collectBooks"});
$("journal").onclick = () => run("journal", "jmsg", "받는 중… (1분 안쪽)", {type: "collectNow"});
$("plan").onclick = () => run("plan", "pmsg", "받는 중… 위하고 화면이 잠깐 앞에 떴다 닫힙니다. 끝날 때까지 다른 탭으로 옮기지 마세요.", {type: "collectPlan", months: months()});
$("closing").onclick = () => run("closing", "cmsg", "이 화면에서 [조회]를 누르고 15초 동안 받는 중… 화면을 닫지 마세요.", {type: "collectClosing"});
$("hr").onclick = () => run("hr", "hmsg", "이 화면에서 [조회]를 누르고 15초 동안 받는 중… 화면을 닫지 마세요.", {type: "collectHr"});
$("ye").onclick = () => run("ye", "ymsg", "이 화면에서 [조회]를 누르고 15초 동안 받는 중… 화면을 닫지 마세요.", {type: "collectYearEnd"});
$("folder").onclick = () => { void chrome.tabs.create({url: chrome.runtime.getURL("saver.html")}); };
monthsSel().onchange = () => { void chrome.storage.local.set({planMonths: months()}); };
void show();
