const $ = (id) => document.getElementById(id);
for (let i = 1; i <= 12; i++) $("months").add(new Option(String(i), String(i)));

function line(info, what) {
  if (!info) return "아직 받은 적 없음";
  let s = `마지막 저장: ${info.saved}<br>${what(info)}`;
  if (info.checked && info.checked !== info.saved) s += `<br>마지막 확인: ${info.checked} (바뀐 것 없음)`;
  return s;
}

async function show() {
  const {status = {}, planMonths = 3} = await chrome.storage.local.get(["status", "planMonths"]);
  $("months").value = String(planMonths);
  $("jmsg").innerHTML = line(status["분개장"], (j) => `전표 ${j.slips}건 · ${j.rows}줄`);
  $("pmsg").innerHTML = line(status["자금계획"], (p) => `${p.days}일 · ${p.rows}줄 (${p.seconds}초)`);
  if (status.progress) $("pmsg").innerHTML += `<br>${status.progress}`;
  if (status.error) $("pmsg").innerHTML += `<br><span class="err">${status.error}</span>`;
}

async function run(btn, msgId, label, message) {
  $("all").disabled = $("journal").disabled = $("plan").disabled = true;
  $(msgId).textContent = label;
  const timer = setInterval(show, 2000);
  const r = await chrome.runtime.sendMessage(message);
  clearInterval(timer);
  $("all").disabled = $("journal").disabled = $("plan").disabled = false;
  await show();
  if (r && r.parts) for (const [k, p] of Object.entries(r.parts)) if (p && p.same) $(msgId).innerHTML += `<br>${k}: 바뀐 것 없음`;
  if (r && r.same) $(msgId).innerHTML += "<br>바뀐 것 없음 — 새 파일 만들지 않음";
  if (r && r.error) $(msgId).innerHTML += `<br><span class="err">${r.error}</span>`;
}

$("all").onclick = () => run("all", "amsg", "분개장 → 자금계획 차례로 받는 중…", {type: "collectAll", months: +$("months").value});
$("journal").onclick = () => run("journal", "jmsg", "받는 중… (1분 안쪽)", {type: "collectNow"});
$("plan").onclick = () => run("plan", "pmsg", "받는 중… (한 달에 30초쯤)", {type: "collectPlan", months: +$("months").value});
$("months").onchange = () => chrome.storage.local.set({planMonths: +$("months").value});
show();
