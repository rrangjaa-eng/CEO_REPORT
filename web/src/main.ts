import { checkDoc } from "./collect/docs";
import { fetchFromExtension } from "./collect/extension";
import { exportBackup, importBackup, listDocs, saveDocs } from "./collect/store";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function say(text: string, err = false) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("err", err);
}

function fmtCount(n: unknown) {
  return typeof n === "number" ? n.toLocaleString("ko-KR") + "줄" : "줄 수 모름";
}

async function render() {
  const items = await listDocs();
  const ul = $("list");
  ul.replaceChildren();
  if (!items.length) {
    const li = document.createElement("li");
    li.innerHTML = "<b>없음</b><span>위하고에서 확장의 [모두 받기]를 누른 뒤 [확장에서 받기]를 누르세요.</span>";
    ul.append(li);
    return;
  }
  for (const it of items) {
    const li = document.createElement("li");
    const k = document.createElement("b");
    k.textContent = it.doc.종류;
    const v = document.createElement("span");
    v.textContent = `${it.doc.회사 ?? "회사 모름"} · ${fmtCount(it.doc.줄수)}`;
    const small = document.createElement("small");
    small.textContent = `위하고에서 받은 때 ${it.doc.수집시각 ?? "모름"}`;
    v.append(small);
    li.append(k, v);
    ul.append(li);
  }
}

async function who() {
  try {
    const r = await fetch("/api/me", { cache: "no-store" });
    const j = (await r.json()) as { email?: string };
    $("who").textContent = j.email ? `${j.email} 로 로그인됨` : "로그인 정보를 모름";
  } catch {
    $("who").textContent = "로그인 정보를 모름";
  }
}

$("pull").addEventListener("click", async () => {
  const b = $<HTMLButtonElement>("pull");
  b.disabled = true;
  say("확장에서 받는 중…");
  try {
    const { version, items } = await fetchFromExtension();
    const good = [];
    const bad: string[] = [];
    for (const it of items) {
      const c = checkDoc(it.doc);
      if (c.ok) good.push(c.doc);
      else bad.push(`${it.name}: ${c.reason}`);
    }
    await saveDocs(good);
    await render();
    say(`확장 ${version}에서 ${good.length}개 받음` + (bad.length ? ` · 쓰지 않음 ${bad.length}개 (${bad.join(" / ")})` : ""), bad.length > 0);
  } catch (e) {
    say(String((e as Error).message ?? e), true);
  } finally {
    b.disabled = false;
  }
});

$("export").addEventListener("click", async () => {
  const blob = await exportBackup();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  const d = new Date();
  a.download = `CEO보고_백업_${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  say("백업 파일을 내려받았습니다. 본인만 쓰는 폴더에 두세요.");
});

$<HTMLInputElement>("import").addEventListener("change", async (ev) => {
  const f = (ev.target as HTMLInputElement).files?.[0];
  if (!f) return;
  try {
    const n = await importBackup(f);
    await render();
    say(`백업에서 ${n}개를 되살렸습니다.`);
  } catch (e) {
    say(String((e as Error).message ?? e), true);
  }
});

void who();
void render();
