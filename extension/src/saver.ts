// 저장 폴더 고르기·허용 창. 배경이 폴더에 바로 쓰지 못한 파일(pendingSaves)을 여기서 쓴다 (단추 클릭 = 사용자 허용).
import {getFolder, setFolder, writeToFolder} from "./folder";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
interface PendingSave { name: string; text: string }

async function pending(): Promise<PendingSave[]> {
  const {pendingSaves = []} = (await chrome.storage.local.get("pendingSaves")) as {pendingSaves?: PendingSave[]};
  return pendingSaves;
}

async function show(extra = ""): Promise<void> {
  const dir = await getFolder();
  const list = await pending();
  let html = dir ? `지금 저장 폴더: <b>${dir.name}</b>` : `<span class="err">저장 폴더를 아직 고르지 않았습니다.</span>`;
  if (list.length) html += `<br>저장 기다리는 파일 ${list.length}개: ${list.map((p) => p.name).join(", ")}`;
  $("msg").innerHTML = html + (extra ? "<br>" + extra : "");
  $("allow").hidden = !(dir && list.length);
}

async function flush(ask: boolean): Promise<{saved: number; left: number}> {
  const list = await pending();
  const done: PendingSave[] = [];
  for (const p of list) {
    const r = await writeToFolder(p.name, p.text, ask);
    if (r === "ok") done.push(p);
  }
  // 2차 P1-7 (2026-11-15): 쓰는 동안 배경이 새로 넣은 파일을 잃지 않게, 대기열을 다시 읽어 방금 쓴 것만 뺀다
  // (예전엔 처음 읽은 목록으로 대기열을 통째로 다시 써서 새 파일이 사라졌음)
  const now = await pending();
  const left = now.filter((q) => !done.some((p) => p.name === q.name && p.text === q.text));
  await chrome.storage.local.set({pendingSaves: left});
  if (done.length) void chrome.runtime.sendMessage({type: "folderSaved", names: done.map((p) => p.name)});
  return {saved: done.length, left: left.length};
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
    if ((e as Error).name !== "AbortError") await show(`<span class="err">${(e as Error).message}</span>`);
  }
};

$("allow").onclick = async () => {
  const r = await flush(true);
  await show(r.left ? `<span class="err">${r.left}개를 저장하지 못했습니다. 폴더를 다시 골라 주세요.</span>` : `<span class="ok">${r.saved}개 저장했습니다.</span>`);
  if (!r.left) setTimeout(() => window.close(), 1500);
};

void (async () => {
  const r = await flush(false);   // 이미 허용돼 있으면 바로 쓴다
  await show(r.saved ? `<span class="ok">${r.saved}개 저장했습니다.</span>` : "");
  if (r.saved && !r.left && new URLSearchParams(location.search).get("auto")) setTimeout(() => window.close(), 1200);
})();
