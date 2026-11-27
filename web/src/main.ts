import { forecastRecord, type Accuracy } from "./calc/accuracy";
import { checkDoc } from "./collect/docs";
import { fetchFromExtension } from "./collect/extension";
import { readPicked, summarize, type FolderFile } from "./collect/folder";
import { buildConvInput, nameOf, seoulDate, seoulNow } from "./collect/inputs";
import { exportBackup, hasForecast, importBackup, lastForecastBefore, listDocs, loadFolder, replaceFolder, saveDocs, saveForecast } from "./collect/store";
import { won } from "./model/util";
import { makeReport, vsForecast, type Kind } from "./pipeline";
import { renderReport, renderStop } from "./report/report";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function say(id: string, text: string, err = false) {
  const el = $(id);
  el.textContent = text;
  el.classList.toggle("err", err);
}

const errText = (e: unknown) => String((e as Error)?.message ?? e);

function fmtCount(n: unknown) {
  return typeof n === "number" ? n.toLocaleString("ko-KR") + "줄" : "줄 수 모름";
}

function row(k: string, v: string, small?: string): HTMLLIElement {
  const li = document.createElement("li");
  const b = document.createElement("b");
  b.textContent = k;
  const span = document.createElement("span");
  span.textContent = v;
  if (small) {
    const s = document.createElement("small");
    s.textContent = small;
    span.append(s);
  }
  li.append(b, span);
  return li;
}

/** ms → 'YYYY-MM-DD HH:MM' (서울) */
const when = (ms: number) => (Number.isFinite(ms) && Math.abs(ms) <= 8.64e15 ? seoulNow(ms).slice(0, 16) : "알 수 없음");

// ── 확장 자료 ──────────────────────────────────────────────

async function renderDocs() {
  const items = await listDocs();
  const ul = $("list");
  ul.replaceChildren();
  if (!items.length) {
    ul.append(row("없음", "위하고에서 확장의 [모두 받기]를 누른 뒤 [확장에서 받기]를 누르세요."));
    return;
  }
  for (const it of items) {
    ul.append(row(it.doc.종류, `${it.doc.회사 ?? "회사 모름"} · ${fmtCount(it.doc.줄수)}`,
      `${nameOf(it.doc, it.name)} · 위하고에서 받은 때 ${it.doc.수집시각 ?? "모름"}`));
  }
}

$("pull").addEventListener("click", async () => {
  const b = $<HTMLButtonElement>("pull");
  b.disabled = true;
  say("status", "확장에서 받는 중…");
  try {
    const { version, items } = await fetchFromExtension();
    const good = [];
    const names: string[] = [];
    const bad: string[] = [];
    for (const it of items) {
      const c = checkDoc(it.doc);
      if (c.ok) { good.push(c.doc); names.push(String(it.name ?? "")); }
      else bad.push(`${it.name}: ${c.reason}`);
    }
    const wrote = await saveDocs(good, new Date(), names);
    await renderDocs();
    const kept = good.length - wrote;
    say("status", `확장 ${version}에서 ${good.length}개 받음` + (kept ? ` · 이미 더 새 것이 있어 그대로 둔 것 ${kept}개` : "")
      + (bad.length ? ` · 쓰지 않음 ${bad.length}개 (${bad.join(" / ")})` : ""), bad.length > 0);
  } catch (e) {
    say("status", errText(e), true);
  } finally {
    b.disabled = false;
  }
});

// ── 보고 폴더 ──────────────────────────────────────────────

async function renderFolder() {
  const { files, importedAt } = await loadFolder();
  const ul = $("folderList");
  ul.replaceChildren();
  if (!files.length) {
    ul.append(row("없음", "아직 불러온 폴더가 없습니다."));
    return;
  }
  for (const g of summarize(files)) ul.append(row(g.folder, `${g.count}개`, `가장 늦게 고친 파일 ${when(g.newest)}`));
  if (importedAt) ul.append(row("불러온 때", when(Date.parse(importedAt))));
}

let folderBusy = false;
async function takeFolder(picked: { rel: string; file: File }[]) {
  // 읽는 중에 또 고르면 늦게 끝난 쪽이 저장돼 안내와 어긋나므로, 하나가 끝날 때까지 받지 않는다
  if (folderBusy) { say("folderStatus", "앞서 고른 폴더를 아직 읽는 중입니다. 끝난 뒤 다시 골라 주세요.", true); return; }
  folderBusy = true;
  try { await takeFolderNow(picked); } finally { folderBusy = false; }
}

async function takeFolderNow(picked: { rel: string; file: File }[]) {
  say("folderStatus", "폴더를 읽는 중…");
  try {
    const { files, skipped, droppedRoots } = await readPicked(picked);
    if (!files.length) {
      say("folderStatus", "고른 폴더 안에 '입력'이나 '수집' 폴더가 없습니다. 보고 폴더(또는 그 위 폴더)를 고르세요.", true);
      return;
    }
    await replaceFolder(files);
    await renderFolder();
    const n = (p: string) => files.filter((f: FolderFile) => f.path.startsWith(p)).length;
    say("folderStatus", `불러옴: 입력 ${n("입력/")}개 · 수집 ${n("수집/")}개` + (skipped ? ` (입력·수집 밖이거나 쓰지 않는 파일 ${skipped}개는 뺌)` : "")
      + " — 예전에 불러온 폴더는 이것으로 바뀌었습니다."
      + (droppedRoots.length ? ` 보고 폴더가 여럿이라 가장 새로 고친 것만 썼습니다 (쓰지 않음: ${droppedRoots.join(", ")}).` : ""));
  } catch (e) {
    say("folderStatus", errText(e), true);
  }
}

$<HTMLInputElement>("folder").addEventListener("change", async (ev) => {
  const input = ev.target as HTMLInputElement;
  const list = [...(input.files ?? [])].map((file) => ({ rel: file.webkitRelativePath || file.name, file }));
  await takeFolder(list);
  input.value = "";
});

/** 끌어 놓은 폴더 안 파일 모두 (경로 포함). */
async function walkEntry(entry: FileSystemEntry, out: { rel: string; file: File }[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
    out.push({ rel: entry.fullPath.replace(/^\//, ""), file });
  } else if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
      if (!batch.length) break;
      for (const e of batch) await walkEntry(e, out);
    }
  }
}

// 상자 밖에 떨어뜨려도 크롬이 파일을 열며 페이지를 떠나지 않게
document.addEventListener("dragover", (ev) => ev.preventDefault());
document.addEventListener("drop", (ev) => ev.preventDefault());
const drop = $("drop");
drop.addEventListener("dragover", (ev) => { ev.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", async (ev) => {
  ev.preventDefault();
  drop.classList.remove("over");
  const entries = [...(ev.dataTransfer?.items ?? [])].map((it) => it.webkitGetAsEntry()).filter((e): e is FileSystemEntry => !!e);
  const out: { rel: string; file: File }[] = [];
  try {
    for (const e of entries) await walkEntry(e, out);
  } catch (e) {
    say("folderStatus", "끌어 놓은 폴더를 읽지 못함: " + errText(e), true);
    return;
  }
  await takeFolder(out);
});

// ── 보고서 만들기 ──────────────────────────────────────────

const kindOf = (): Kind => (($<HTMLFormElement>("makeForm").elements.namedItem("kind") as RadioNodeList).value === "monthly" ? "monthly" : "weekly");

function syncKind() {
  $("paydayField").hidden = kindOf() !== "weekly";
}
for (const r of document.querySelectorAll<HTMLInputElement>("input[name=kind]")) r.addEventListener("change", syncKind);

function showView(on: boolean) {
  $("home").hidden = on;
  $("view").hidden = !on;
  window.scrollTo(0, 0);
}

function vsTable(a: Accuracy, prevAsof: string): HTMLElement {
  const sec = $("vsBox");
  sec.replaceChildren();
  sec.className = "vs";
  const h2 = document.createElement("h2");
  h2.textContent = "지난 예상 대비 실제";
  const p = document.createElement("p");
  p.className = "note";
  p.textContent = `${prevAsof} 보고의 예상과 ${a.from} ~ ${a.to} 통장 입출금 (차이 = 실제 − 예상, 계좌간이체 뺌)`;
  const t = document.createElement("table");
  const tr = (cells: string[], th = false) => {
    const r = document.createElement("tr");
    for (const c of cells) {
      const el = document.createElement(th ? "th" : "td");
      el.textContent = c;
      r.append(el);
    }
    return r;
  };
  const thead = document.createElement("thead");
  thead.append(tr(["", "예상(확정)", "예상(전체)", "실제", "차이(전체)"], true));
  const tb = document.createElement("tbody");
  const side = (label: string, s: Accuracy["in"]) =>
    tr([label + (s.unknown_n ? ` (금액 모름 ${s.unknown_n}건)` : ""), won(s.firm), won(s.all), won(s.actual), won(s.diff_all)]);
  tb.append(side("입금", a.in), side("출금", a.out),
    tr(["끝 잔액", won(a.end.firm), won(a.end.all), won(a.end.actual), won(a.end.diff_all)]));
  t.append(thead, tb);
  const wrap = document.createElement("div");
  wrap.className = "tw";
  wrap.append(t);
  sec.append(h2, p, wrap);
  sec.hidden = false;
  return sec;
}

$<HTMLFormElement>("makeForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const b = $<HTMLButtonElement>("make");
  const kind = kindOf();
  const asof = $<HTMLInputElement>("asof").value;
  const payday = kind === "weekly" ? $<HTMLInputElement>("payday").value || null : null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(asof)) { say("makeStatus", "기준일을 넣으세요", true); return; }
  if (payday && payday <= asof) { say("makeStatus", `출금일은 기준일(${asof}) 뒤여야 합니다. 출금하는 날 아침에 만들면 기준일을 그 전날로 넣으세요.`, true); return; }
  b.disabled = true;
  say("makeStatus", "만드는 중…");
  try {
    const folder = await loadFolder();
    const docs = await listDocs();
    if (!folder.files.length && !docs.length) throw new Error("자료가 없습니다. 먼저 보고 폴더를 불러오세요.");
    const inp = buildConvInput(folder.files, docs.map((d) => ({ doc: d.doc, name: d.name ?? null })));
    const nowMs = Date.now();
    const made = await makeReport(inp, kind, asof, payday, seoulNow(nowMs));
    const body = $("reportBody");
    body.replaceChildren();
    $("vsBox").hidden = true;
    const title = kind === "weekly" ? "주간 보고" : "월간 보고";
    if (!made.ok || !made.R) {
      body.append(renderStop(made.stop, title));
    } else {
      body.append(renderReport(made.R, kind, { made: seoulNow(nowMs).slice(0, 16) }));
      const prev = await lastForecastBefore(asof);
      if (prev && made.data) vsTable(vsForecast(prev, made.data, made.R), prev.asof);
    }
    $("logCode").textContent = `(코드 ${made.conv.code} · 변환 ${Math.round(made.ms.convert)}ms · 계산 ${Math.round(made.ms.report)}ms)`;
    $("log").textContent = [...made.conv.lines, ...made.notes].join("\n");
    showView(true);
    say("makeStatus", "");
    // 예상 기록은 그 기준일에 처음 만든 것만 남긴다(지난 기준일을 다시 만들면 이미 실제가 섞인 '예상'이 되므로)
    if (made.ok && made.R && !(await hasForecast(asof))) await saveForecast(forecastRecord(made.R));
  } catch (e) {
    say("makeStatus", errText(e), true);
  } finally {
    b.disabled = false;
  }
});

$("back").addEventListener("click", (ev) => { ev.preventDefault(); showView(false); });
$("print").addEventListener("click", () => window.print());

// ── 백업 ──────────────────────────────────────────────────

$("export").addEventListener("click", async () => {
  let blob: Blob;
  try {
    blob = await exportBackup();
  } catch (e) {
    say("backupStatus", errText(e), true);
    return;
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `CEO보고_백업_${seoulDate(Date.now()).replace(/-/g, "")}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  say("backupStatus", "백업 파일을 내려받았습니다. 본인만 쓰는 폴더에 두세요.");
});

$<HTMLInputElement>("import").addEventListener("change", async (ev) => {
  const input = ev.target as HTMLInputElement;
  const f = input.files?.[0];
  if (!f) return;
  try {
    const n = await importBackup(f);
    await renderDocs();
    await renderFolder();
    say("backupStatus", `백업에서 ${n}개를 되살렸습니다. 더 새로 받은 같은 자료와 더 늦게 불러온 폴더는 그대로 뒀습니다.`);
  } catch (e) {
    say("backupStatus", errText(e), true);
  } finally {
    input.value = ""; // 같은 파일을 다시 골라도 불러오게
  }
});

// ── 시작 ──────────────────────────────────────────────────

async function who() {
  try {
    const r = await fetch("/api/me", { cache: "no-store" });
    const j = (await r.json()) as { email?: string };
    $("who").textContent = j.email ? `${j.email} 로 로그인됨` : "로그인 정보를 모름";
  } catch {
    $("who").textContent = "로그인 정보를 모름";
  }
}

$<HTMLInputElement>("asof").value = seoulDate(Date.now());
syncKind();
void who();
void renderDocs();
void renderFolder();
