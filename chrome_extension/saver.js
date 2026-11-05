// 저장 폴더 고르기·허용 창. 배경이 폴더에 바로 쓰지 못한 파일(pendingSaves)을 여기서 쓴다 (단추 클릭 = 사용자 허용).
const $ = (id) => document.getElementById(id);

async function pending() {
  const {pendingSaves = []} = await chrome.storage.local.get("pendingSaves");
  return pendingSaves;
}

async function show(extra = "") {
  const dir = await getFolder();
  const list = await pending();
  let html = dir ? `지금 저장 폴더: <b>${dir.name}</b>` : `<span class="err">저장 폴더를 아직 고르지 않았습니다.</span>`;
  if (list.length) html += `<br>저장 기다리는 파일 ${list.length}개: ${list.map((p) => p.name).join(", ")}`;
  $("msg").innerHTML = html + (extra ? "<br>" + extra : "");
  $("allow").hidden = !(dir && list.length);
}

async function flush(ask) {
  const list = await pending();
  const left = [];
  let saved = 0;
  for (const p of list) {
    const r = await writeToFolder(p.name, p.text, ask);
    if (r === "ok") saved++; else left.push(p);
  }
  await chrome.storage.local.set({pendingSaves: left});
  if (saved) chrome.runtime.sendMessage({type: "folderSaved", names: list.filter((p) => !left.includes(p)).map((p) => p.name)});
  return {saved, left: left.length};
}

$("pick").onclick = async () => {
  try {
    const dir = await window.showDirectoryPicker({id: "ceoReportWehago", mode: "readwrite"});
    if (dir.name !== "위하고" && !confirm(`고른 폴더 이름이 '${dir.name}' 입니다. 보통은 F:\\CLAUDE\\CEO_REPORT\\수집\\위하고 를 고릅니다. 이 폴더로 할까요?`)) return;
    await setFolder(dir);
    const r = await flush(true);
    await show(r.saved ? `<span class="ok">${r.saved}개 저장했습니다.</span>` : `<span class="ok">폴더를 정했습니다.</span>`);
    if (r.saved && !r.left) setTimeout(() => window.close(), 1500);
  } catch (e) {
    if (e.name !== "AbortError") await show(`<span class="err">${e.message}</span>`);
  }
};

$("allow").onclick = async () => {
  const r = await flush(true);
  await show(r.left ? `<span class="err">${r.left}개를 저장하지 못했습니다. 폴더를 다시 골라 주세요.</span>` : `<span class="ok">${r.saved}개 저장했습니다.</span>`);
  if (!r.left) setTimeout(() => window.close(), 1500);
};

(async () => {
  const r = await flush(false);   // 이미 허용돼 있으면 바로 쓴다
  await show(r.saved ? `<span class="ok">${r.saved}개 저장했습니다.</span>` : "");
  if (r.saved && !r.left && new URLSearchParams(location.search).get("auto")) setTimeout(() => window.close(), 1200);
})();
