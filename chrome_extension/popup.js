const $ = (id) => document.getElementById(id);
for (let i = 1; i <= 12; i++) $("months").add(new Option(String(i), String(i)));

function line(info, what) {
  if (!info) return "아직 받은 적 없음";
  let s = `마지막 저장: ${info.saved}<br>${what(info)}` + (info.where ? `<br>저장 위치: ${info.where}` : "");
  if (info.checked && info.checked !== info.saved) s += `<br>마지막 확인: ${info.checked} (바뀐 것 없음)`;
  return s;
}

async function show() {
  try {
    const dir = await getFolder();
    const {pendingSaves = []} = await chrome.storage.local.get("pendingSaves");
    $("fmsg").innerHTML = (dir ? `저장 폴더: <b>${dir.name}</b>` : `<span class="err">저장 폴더를 아직 고르지 않았습니다 (지금은 다운로드 폴더에 저장)</span>`)
      + (pendingSaves.length ? `<br><span class="err">저장 허용 기다리는 파일 ${pendingSaves.length}개 — 아래 단추를 눌러 주세요</span>` : "");
  } catch (e) { $("fmsg").textContent = ""; }
  const {status = {}, planMonths = 3} = await chrome.storage.local.get(["status", "planMonths"]);
  $("months").value = String(planMonths);
  $("jmsg").innerHTML = line(status["분개장"], (j) => `전표 ${j.slips}건 · ${j.rows}줄`);
  $("pmsg").innerHTML = line(status["자금계획"], (p) => `${p.months}개월 · ${p.rows}줄 (${p.seconds}초)`);
  if (status.progress) $("pmsg").innerHTML += `<br>${status.progress}`;
  const {closingLog = []} = await chrome.storage.local.get("closingLog");
  const {hrLog = []} = await chrome.storage.local.get("hrLog");
  const {yearEndLog = []} = await chrome.storage.local.get("yearEndLog");
  $("ymsg").innerHTML = yearEndLog.slice(0, 2).map((c) => `연말정산 ${c.at.slice(5, 16)} · ${c.screen || c.code} · ${c.file}`).join("<br>");
  $("hmsg").innerHTML = hrLog.slice(0, 2).map((c) => `인사·급여 ${c.at.slice(5, 16)} · ${c.screen || c.code} · ${c.file}`).join("<br>");
  $("cmsg").innerHTML = closingLog.slice(0, 2).map((c) => `결산 ${c.at.slice(5, 16)} · ${c.screen || c.code} · ${c.file}`).join("<br>");
  const {booksLog} = await chrome.storage.local.get("booksLog");
  $("bmsg").innerHTML = booksLog ? `마지막: ${booksLog.at.slice(5, 16)} · ${booksLog.done.length}개 화면 (${booksLog.seconds}초)` + (booksLog.same ? ` · ${booksLog.same}개는 바뀐 것 없음` : "")
    + (booksLog.fails.length ? `<br><span class="err">${booksLog.fails.join("<br>")}</span>` : "") : "아직 받은 적 없음";
  if (status.progress && /^결산·인사급여/.test(status.progress)) $("bmsg").innerHTML += `<br>${status.progress}`;
  if (status.error) $("pmsg").innerHTML += `<br><span class="err">${status.error}</span>`;
}

async function run(btn, msgId, label, message) {
  $("books").disabled = $("all").disabled = $("journal").disabled = $("plan").disabled = $("closing").disabled = $("hr").disabled = $("ye").disabled = true;
  $(msgId).textContent = label;
  const timer = setInterval(show, 2000);
  const r = await chrome.runtime.sendMessage(message);
  clearInterval(timer);
  $("books").disabled = $("all").disabled = $("journal").disabled = $("plan").disabled = $("closing").disabled = $("hr").disabled = $("ye").disabled = false;
  await show();
  if (r && r.parts) for (const [k, p] of Object.entries(r.parts)) if (p && p.same) $(msgId).innerHTML += `<br>${k}: 바뀐 것 없음`;
  if (r && r.same) $(msgId).innerHTML += "<br>바뀐 것 없음 — 새 파일 만들지 않음";
  if (r && r.error) $(msgId).innerHTML += `<br><span class="err">${r.error}</span>`;
}

$("all").onclick = () => run("all", "amsg", "분개장 → 대조 화면(시산표·차입금 등) → 자금계획 차례로 받는 중… 위하고 화면이 잠깐 앞에 떴다 닫힙니다.", {type: "collectAll", months: +$("months").value});
$("books").onclick = () => run("books", "bmsg", "받는 중… 위하고 화면이 1~2분 앞에 떴다 닫힙니다. 끝날 때까지 다른 탭으로 옮기지 마세요.", {type: "collectBooks"});
$("journal").onclick = () => run("journal", "jmsg", "받는 중… (1분 안쪽)", {type: "collectNow"});
$("plan").onclick = () => run("plan", "pmsg", "받는 중… 위하고 화면이 잠깐 앞에 떴다 닫힙니다. 끝날 때까지 다른 탭으로 옮기지 마세요.", {type: "collectPlan", months: +$("months").value});
$("closing").onclick = () => run("closing", "cmsg", "이 화면에서 [조회]를 누르고 15초 동안 받는 중… 화면을 닫지 마세요.", {type: "collectClosing"});
$("hr").onclick = () => run("hr", "hmsg", "이 화면에서 [조회]를 누르고 15초 동안 받는 중… 화면을 닫지 마세요.", {type: "collectHr"});
$("ye").onclick = () => run("ye", "ymsg", "이 화면에서 [조회]를 누르고 15초 동안 받는 중… 화면을 닫지 마세요.", {type: "collectYearEnd"});
$("folder").onclick = () => chrome.tabs.create({url: chrome.runtime.getURL("saver.html")});
$("months").onchange = () => chrome.storage.local.set({planMonths: +$("months").value});
show();
