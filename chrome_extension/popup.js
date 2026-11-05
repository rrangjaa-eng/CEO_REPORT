const $ = (id) => document.getElementById(id);
async function show() {
  const {status = {}, auto = false} = await chrome.storage.local.get(["status", "auto"]);
  $("auto").checked = auto;
  const j = status["분개장"];
  let html = j ? `마지막 저장: ${j.saved}<br>전표 ${j.slips}건 · ${j.rows}줄` + (j.checked && j.checked !== j.saved ? `<br>마지막 확인: ${j.checked} (바뀐 것 없음)` : "") : "아직 받은 적 없음";
  if (status.error) html += `<br><span class="err">${status.error}</span>`;
  $("msg").innerHTML = html;
}
$("now").onclick = async () => {
  $("now").disabled = true; $("msg").textContent = "받는 중… (최대 2분)";
  const r = await chrome.runtime.sendMessage({type: "collectNow"});
  $("now").disabled = false;
  await show();
  if (r && r.error) $("msg").innerHTML += `<br><span class="err">${r.error}</span>`;
};
$("auto").onchange = (e) => chrome.runtime.sendMessage({type: "setAuto", on: e.target.checked});
show();
