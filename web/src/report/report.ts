// 대표 보고 화면 (주간·월간). R(계산 결과)만 받아 문서 한 장을 만든다. 막는 까닭(stop)이 있으면 보고 대신 까닭만.
// 무엇을 싣나 (render.py 대표판 _first_screen 기준, 사용자 결정 그대로):
//   주간  요약 4칸 · 1 자금 흐름(출금일 목록 · 다음 주 지급 · 기간별 여유 자금 · 예상 잔액 그림) · 2 이번 달 매출·매입
//         — 주간엔 이번 달 영업이익을 싣지 않는다 (사용자 2026-11-16: 마감 전 영업이익은 틀리기 쉬움)
//   월간  요약 4칸 · 1 자금 흐름(이번 달 흐름 · 앞으로 여유 자금 · 그림 · 지난 미처리) · 2 매출·매입 · 3 회사 수익 · 4 팀별 수익
// 숫자 칸은 모두 fmt.money (data-k 로 어디서 온 숫자인지 남김 → 시험이 R 과 1원까지 맞춤).
import type { Obj } from "../calc/ctx";
import { bookDate } from "../calc/gate";
import { unissuedDue, withVat } from "../calc/projects";
import { addDays, daysBetween, monthEnd, type IsoDate } from "../model/dates";
import { pyFixed, pyRound } from "../model/py";
import { balanceChart, type BalPoint } from "./chart";
import {
  catCell, companyPl, depInto, missingContracts, monthFlow, monthNp, monthSeries, nextWeekGroups, pname, teamAllocate,
  teamBuild, teamYtdAlloc, vsLastWeek, weekOutflows, type Nonop, type TeamRow, type TeamTable,
} from "./derive";
import { day, md, money, pct, won, ymText } from "./fmt";
import { cat, h, raw, type Child, type Html } from "./html";

export type ReportKind = "weekly" | "monthly";
export interface ReportOpts { stop?: string[] | null; made?: string | null }

// ── 공용 조각 (표 · 숫자 칸 · 절) ─────────────────────────────

export interface Col { t: string; num?: boolean; sub?: string }
export type Cell = Child;
export interface Row { cells: Cell[]; cls?: string }

/** 표 하나 (모든 표가 이것을 쓴다). 숫자 칸은 오른쪽 맞춤·고정폭 숫자. 넓으면 자기 상자 안에서만 옆으로 밀린다. */
export function table(cols: Col[], rows: (Row | Cell[])[], opts: { cls?: string; total?: Cell[]; empty?: string; caption?: string } = {}): Html {
  const head = h("tr", null, cols.map((c) => h("th", { class: c.num ? "n" : null, scope: "col" }, c.t, c.sub ? h("small", null, c.sub) : null)));
  const tr = (cells: Cell[], cls?: string) =>
    h("tr", { class: cls }, cells.map((c, i) => h("td", { class: cols[i]?.num ? "n" : null, "data-l": cols[i]?.t || null }, c)));
  const body: Html[] = rows.map((r) => (Array.isArray(r) ? tr(r) : tr(r.cells, r.cls)));
  if (opts.total) body.push(tr(opts.total, "tot"));
  if (!rows.length && !opts.total) body.push(h("tr", null, h("td", { colspan: cols.length, class: "empty" }, opts.empty ?? "해당 없음")));
  return h("div", { class: "tw" }, h("table", { class: opts.cls },
    opts.caption ? h("caption", null, opts.caption) : null, h("thead", null, head), h("tbody", null, body)));
}

export interface Fig { label: string; value: Html; foot?: Child }

/** 요약 숫자 줄 (2~4칸). */
export function figures(cells: Fig[], cls = ""): Html {
  return h("dl", { class: ("figs " + cls).trim() }, cells.map((c) =>
    h("div", null, h("dt", null, c.label), h("dd", null, c.value), c.foot ? h("dd", { class: "foot" }, c.foot) : null)));
}

function section(no: number, title: string, ...body: Child[]): Html {
  return h("section", { class: "sec" }, h("h2", null, h("span", { class: "no" }, `${no}.`), title), ...body);
}

function sub(title: string, extra?: string): Html {
  return h("h3", null, title, extra ? h("small", null, extra) : null);
}

function note(text: Child, cls = ""): Html {
  return h("p", { class: ("note " + cls).trim() }, text);
}

function warn(text: string): Html {
  return h("p", { class: "warn" }, text);
}

// ── 머리 ────────────────────────────────────────────────────

function bankLagNote(R: Obj): string {
  const v = (R["auto_facts"] || {})["last_bank"];
  if (!v) return "";
  const lb = String(v).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(lb)) return "";
  const gap = daysBetween(lb, R["asof"]);
  if (gap <= 7) return "";
  if (gap > 45) {
    return `장부의 마지막 통장 거래가 ${lb} (기준일보다 ${gap}일 전)입니다 — 지난 기수(작년) 분개장을 받았거나 장부 입력이 크게 밀렸습니다. `
      + "위하고에서 올해 기수 분개장을 다시 받기 전에는 이 보고의 실적·잔액을 믿지 마세요.";
  }
  return `장부에 들어간 마지막 통장 거래가 ${lb} (기준일보다 ${gap}일 전)입니다 — 그 뒤 통장 입출금은 아직 장부에 없어 실적·지급에 빠졌을 수 있습니다.`;
}

/** gate.sources_line */
function sourcesLine(R: Obj): string {
  const parts: string[] = [];
  const bd = bookDate(R as never);
  const v = (R["auto_facts"] || {})["last_bank"];
  const lb = v ? String(v).slice(0, 10) : null;
  parts.push(bd ? `분개장 ${bd}` + (lb && lb < bd ? ` (통장 거래 ${lb}까지 입력)` : "") : "분개장 날짜 모름");
  const fp = R["fundplan"];
  if (fp && fp["used"]) {
    const ms = ((fp["months"] || []) as string[]).slice().sort();
    parts.push(`자금계획서 ${fp["stamp"]} 받음` + (ms.length ? ` (${ms[0]}~${ms[ms.length - 1]})` : ""));
  } else {
    parts.push("자금계획서 미반영");
  }
  return "사용한 자료: " + parts.join(" · ");
}

function header(R: Obj, kind: ReportKind, made: string | null | undefined): Html {
  const st = R["settings"] || {};
  const [p0, p1] = R["period"] as [IsoDate, IsoDate];
  const asofs = ((R["s7"]?.["asof"] || []) as Obj[]).map((a) => `${a["name"]} ${a["date"] ?? "날짜 없음"}`).join(" · ");
  return h("header", { class: "doc-h" },
    kind === "weekly" ? h("table", { class: "sign", "aria-label": "결재" },
      h("tr", null, h("th", { rowspan: 2, class: "sv" }, "결재"), h("th", null, "담당"), h("th", null, "대표이사")),
      h("tr", { class: "sg" }, h("td", null, ""), h("td", null, ""))) : null,
    h("p", { class: "co" }, String(st["회사명"] || "")),
    h("h1", null, kind === "weekly" ? "주간 보고" : "월간 보고"),
    h("dl", { class: "meta" },
      h("div", null, h("dt", null, "보고 기준일"), h("dd", null, R["asof"])),
      h("div", null, h("dt", null, "집계 기간"), h("dd", null, `${p0} ~ ${p1}`)),
      h("div", null, h("dt", null, "금액 단위"), h("dd", null, "원")),
      made ? h("div", null, h("dt", null, "작성"), h("dd", null, made)) : null),
    h("p", { class: "src" }, `자료 기준일: ${asofs}`, h("br", null), sourcesLine(R)));
}

// ── 공통 계산 조각 ───────────────────────────────────────────

const periods = (R: Obj) => ((R["s2"]["periods"] || []) as Obj[]).map((p, i) => [p, i] as const).filter(([p]) => !p["pick"]);

function availFig(R: Obj, which: "first" | "last"): Fig | null {
  const ps = periods(R);
  if (!ps.length) return null;
  const [p, i] = which === "first" ? ps[0]! : ps[ps.length - 1]!;
  return {
    label: which === "first" && R["kind"] === "weekly" ? "이번 주 여유 자금" : `${p["label"]}까지 여유 자금`,
    value: money(p["firm"]["avail"], `R:s2.periods.${i}.firm.avail`, "확인 필요"),
  };
}

function overdueFig(R: Obj): Fig {
  const s5 = R["s5"];
  if (s5["in_missing"] && s5["in_missing"].length) return { label: "입금일 지난 미수금", value: h("span", { class: "na" }, "계산서 자료 없음") };
  if (!s5["overdue"].length) return { label: "입금일 지난 미수금", value: h("span", { class: "none" }, "없음") };
  return { label: "입금일 지난 미수금", value: money(s5["overdue_total"], "R:s5.overdue_total"), foot: `${s5["overdue"].length}건` };
}

/** 금액 칸 + 아래 작은 줄 */
function withSmall(v: Html, ...small: Child[]): Html {
  return cat(v, small.filter(Boolean).map((s) => h("small", null, s)));
}

function availTable(R: Obj): Html {
  const s1 = R["s1"], s2 = R["s2"];
  const runk = s1["restr_unknown"] ? ` (확인 안 됨 ${s1["restr_unknown"]}계좌)` : "";
  const inMiss = s2["in_missing"]?.length ? "계산서 자료 없음" : null;
  const outMiss = s2["out_missing"]?.length ? "지급 자료 없음" : null;
  const rows: Row[] = periods(R).map(([p, i]) => {
    const r = p["firm"];
    const xin = (p["all"]["pin"] ?? 0) - (r["pin"] ?? 0), xout = (p["all"]["pout"] ?? 0) - (r["pout"] ?? 0);
    const rng = p["pick"] || !p["from"] ? `오늘~${p["end"]}` : `${md(p["from"])}~${md(p["end"])}`;
    const sp = p["spend"]?.["avail"];
    const spend = sp === null || sp === undefined || sp === r["avail"] ? null
      : cat("프로젝트 지급 예상 등까지 빼면 ", money(sp, `R:s2.periods.${i}.spend.avail`));
    return {
      cells: [
        withSmall(h("b", null, p["label"]), rng),
        withSmall(money(r["pin"] ?? r["in"], `R:s2.periods.${i}.firm.pin`), inMiss, xin ? cat("예상 +", money(xin, `D:s2.periods.${i}.in_extra`), " 별도") : null),
        withSmall(money(r["pout"] ?? r["out"], `R:s2.periods.${i}.firm.pout`), outMiss, xout ? cat("예상 −", money(xout, `D:s2.periods.${i}.out_extra`), " 별도") : null),
        withSmall(h("b", null, money(r["avail"], `R:s2.periods.${i}.firm.avail`, "확인 필요")), spend),
      ],
    };
  });
  const mc = s2["min_cash"];
  const warns: string[] = [];
  if (s2["out_missing"]?.length) warns.push(`지급 자료 없음: ${s2["out_missing"].join(", ")} — 잔액·여유 자금은 계산하지 않음`);
  if (s2["in_missing"]?.length) warns.push(`계산서 입금 예정 미반영 (자료 없음: ${(s2["in_missing"] as string[]).map((m) => m.split(" (")[0]).join(", ")})`);
  if (s2["vat_unknown_n"]) warns.push(`부가세 미확인 ${s2["vat_unknown_n"]}건 (공급가액만 반영)`);
  return cat(
    sub("기간별 여유 자금", `시작: 오늘 쓸 수 있는 돈 ${s2["start"] === null ? "잔액 미확인" : won(s2["start"]) + "원"}${runk}`),
    table([{ t: "기간" }, { t: "들어올 돈", num: true }, { t: "나갈 돈", num: true }, { t: "여유 자금", num: true }], rows, { cls: "avail reflow" }),
    note(`여유 자금 = 기간 중 잔액이 가장 적을 때 − 최소 보유현금 ${mc !== null && mc !== undefined ? won(mc) : "설정 오류"} · `
      + "확정된 돈과 급여·세금·카드 같은 정기 지출 예상으로 계산 (프로젝트 지급 예상·예상 입금은 '별도'로 따로 적음)"),
    warns.map(warn));
}

/** 자금계획서가 있는 달까지만 그림에 넣는다 (그 뒤 달은 지급이 빠져 잔액이 크게 보임). */
function planMonths(R: Obj): Set<string> {
  const fp = R["fundplan"] || {};
  return new Set([...(fp["months"] || []), ...(fp["received"] || [])] as string[]);
}

function coveredUpTo(R: Obj, to: IsoDate): boolean {
  const have = planMonths(R);
  let m = String(R["asof"]).slice(0, 7);
  const end = to.slice(0, 7);
  while (m <= end) {
    if (!have.has(m)) return false;
    const [y, mm] = m.split("-").map(Number) as [number, number];
    m = mm === 12 ? `${y + 1}-01` : `${y}-${String(mm + 1).padStart(2, "0")}`;
  }
  return true;
}

function bucketLabel(b: Obj, weekNames: Map<string, string>): string {
  if (b["type"] === "week" && weekNames.has(b["to"])) return weekNames.get(b["to"])!;
  const l = String(b["label"]).replace(" (일부)", "*").replace(/\(실적(\+예정)?\)/, "");
  const m = /(\d+)월/.exec(l);
  return m ? `${m[1]}월${l.endsWith("*") ? "*" : ""}` : l;
}

function balanceSection(R: Obj, kind: ReportKind): Html {
  const s2 = R["s2"];
  const src: Obj[] = kind === "weekly" ? s2["buckets"] : monthFlow(R).buckets as unknown as Obj[];
  const weekNames = new Map<string, string>(periods(R).map(([p]) => [p["end"], p["label"]]));
  const lastOk = src.reduce((k, b, i) => (b["to"] ? coveredUpTo(R, b["to"]) : coveredUpTo(R, monthEnd(`${b["ym"]}-01`))) ? i : k, -1);
  const shown = src.slice(0, lastOk + 1);
  const pts: BalPoint[] = shown.map((b) => ({ label: bucketLabel(b, weekNames), firm: b["bal_firm"], all: b["bal_all"] }));
  const fp = R["fundplan"] || {};
  const ms = ((fp["months"] || []) as string[]).slice().sort();
  const cut = shown.length < src.length && ms.length ? `자금계획서가 있는 달(${ms[0]}~${ms[ms.length - 1]})까지만 그림 — 그 뒤는 지급이 빠져 잔액이 크게 보입니다.` : "";
  const startText = kind === "weekly"
    ? `시작: 오늘 쓸 수 있는 돈 ${s2["start"] === null ? "잔액 미확인" : won(s2["start"]) + "원"}`
    : (() => { const f = monthFlow(R); return `${parseInt(f.first.slice(5, 7), 10)}월 1일 쓸 수 있는 돈 ${f.start === null ? "잔액 미확인" : won(f.start) + "원"}에서 시작`; })();
  const noLine = s2["start"] === null || s2["out_missing"]?.length;
  const chart = noLine ? warn(`${s2["out_missing"]?.length ? "지급 자료 없음" : "잔액 미확인"} — 예상 잔액 그림은 그리지 않음`)
    : balanceChart(pts, s2["min_cash"] ?? null);
  // 그림의 표 보기: 같은 숫자를 글자로 (인쇄·색 구분이 어려운 사람용)
  const rows: Row[] = noLine ? [] : shown.map((b, i) => ({
    cells: [pts[i]!.label,
      money(b["bal_firm"], kind === "weekly" ? `R:s2.buckets.${i}.bal_firm` : `D:flow.${i}.bal_firm`),
      money(b["bal_all"], kind === "weekly" ? `R:s2.buckets.${i}.bal_all` : `D:flow.${i}.bal_all`)],
  }));
  return cat(h("div", { class: "keep" }, sub(kind === "weekly" ? "기간별 예상 잔액" : "월별 예상 잔액", startText), chart),
    rows.length ? h("details", { class: "tview" }, h("summary", null, "그림 숫자 보기"),
      table([{ t: "기간" }, { t: "예상 잔액", num: true }, { t: "예상 입출금까지", num: true }], rows)) : null,
    cut ? note(cut) : null,
    kind === "weekly" ? note("4주는 주별, 그 뒤는 월별 (* 일부 기간)") : null);
}

function unissuedBlock(R: Obj): Html {
  const E = R["s5"]["event_unissued"];
  if (E["missing"] || !E["rows"].length) return raw("");
  const rows: Row[] = (E["rows"] as Obj[]).map((y, i) => ({
    cells: [`[${y["P"]["id"]}] ${y["P"]["name"]}`, `${y["days"]}일`, money(withVat(y["unissued"]), `D:unissued.${i}`)],
  }));
  return cat(sub("행사 끝나고 아직 세금계산서를 발행하지 않은 돈"),
    table([{ t: "프로젝트" }, { t: "행사 후", num: true }, { t: "받을 돈 (부가세 포함)", num: true }], rows,
      { total: [`합계 ${rows.length}건`, "", money(unissuedDue(E), "D:unissued.total")] }),
    E["unknown"]?.length ? warn(`확인 필요 ${E["unknown"].length}건 (금액을 몰라 합계에 없음)`) : null);
}

function unissuedFig(R: Obj): Fig {
  const s5 = R["s5"], E = s5["event_unissued"];
  if (E["missing"]) return { label: "행사 후 세금계산서 미발행", value: h("span", { class: "na" }, "계산서 자료 없음") };
  return { label: "행사 후 세금계산서 미발행", value: money(unissuedDue(E), "D:unissued.total"), foot: `받을 돈 (부가세 포함) · ${E["rows"].length}건` };
}

/** 매입 (계산서 기준 공급가액, 증빙월별). 파일이 없으면 미확인. 그 달 줄이 없으면 그 달 계산서가 없는 것(0). */
function buyFig(R: Obj, ym: string): Fig {
  const ev = R["evid_month"] as Record<string, [number, number]> | null;
  const v = ev === null || ev === undefined ? null : (ev[ym] ?? [0, 0])[1];
  return { label: `${ymText(ym)} 매입`, value: money(v, ev && ev[ym] ? `R:evid_month.${ym}.1` : "D:buy.none", "자료 없음"),
    foot: "세금계산서 기준 (부가세 제외)" };
}

function contractLine(R: Obj): Html | null {
  const n = missingContracts(R);
  return n ? note(`계약금액이 없어 지금 예상 이익을 못 낸 프로젝트 ${n}개 — 인트라넷에 계약금액을 넣으면 나옵니다.`) : null;
}

// ── 주간 ────────────────────────────────────────────────────

function weekly(R: Obj): Html {
  const W = weekOutflows(R);
  const P = W.pay;
  const ym = R["s4"]["ym"] as string;
  const { cur, ytd, src, key } = companyPl(R);
  const top = figures([
    { label: `${day(W.fri)} 출금`, value: money(P.total, "D:week.pay.total"), foot: `${P.rows.length}건` },
    availFig(R, "first")!, availFig(R, "last")!, overdueFig(R),
  ].filter(Boolean) as Fig[], "top");
  const payRows: Row[] = P.rows.map((e, i) => {
    const [c, d, na] = catCell(e);
    return { cells: [md(e["date"]), h("b", null, e["desc"] || ""), pname(R, e["project"]),
      cat(c, d ? h("small", { class: na ? "na" : null }, d) : null), money(e["amount"], `D:week.pay.${i}`)] };
  });
  const groups = nextWeekGroups(W.next);
  const unkAll = W.next.unknown_n;
  const gap = W.gap.rows.length ? note(`예정일 지난 장부 미확인 지급 ${W.gap.rows.length}건 ${won(W.gap.total)}원은 목록에서 빼고 자금 표에만 포함`) : null;
  const fund = section(1, "자금 흐름",
    sub(`${day(W.fri)} 출금 목록`, `${P.rows.length}건 · 합계 ${won(P.total)}원`),
    table([{ t: "예정일" }, { t: "거래처" }, { t: "프로젝트" }, { t: "내역" }, { t: "금액", num: true }], payRows,
      { cls: "pay", empty: "이 날 출금 없음", total: P.rows.length ? ["합계", `${P.rows.length}건`, "", "", money(P.total, "D:week.pay.total")] : undefined }),
    gap, note(vsLastWeek(R, P)),
    sub("다음 주 지급 예정", `${day(addDays(W.fri, 1))} ~ ${day(W.end)} · 항목별`),
    table([{ t: "구분" }, { t: "건수", num: true }, { t: "예정일" }, { t: "금액", num: true }, { t: "상태" }],
      groups.map((g, i) => [g.name, `${g.n}건`, g.days,
        cat(money(g.known, `D:week.next.${i}`), g.unknown ? h("small", { class: "na" }, `미확인 ${g.unknown}건`) : null), g.state]),
      { cls: "next", empty: "다음 주 지급 예정 없음", total: groups.length ? ["합계", `${W.next.rows.length}건`, "",
        cat(money(W.next.total, "D:week.next.total"), unkAll ? h("small", { class: "na" }, `+ 금액 미확인 ${unkAll}건`) : null), ""] : undefined }),
    availTable(R), balanceSection(R, "weekly"));
  const sales = section(2, `${ymText(ym)} 매출·매입`,
    figures([
      cur ? { label: `${ymText(ym)} 매출`, value: money(cur["revenue"], `${key}.cur.revenue`),
        foot: cat("올해 누적 ", ytd ? money(ytd["revenue"], `${key}.ytd.revenue`) : h("span", { class: "na" }, "자료 없음")) }
        : { label: `${ymText(ym)} 매출`, value: h("span", { class: "na" }, src ? `자료 없음 (최근 ${src["latest"] || "-"})` : "자료 없음") },
      buyFig(R, ym), unissuedFig(R),
    ]),
    unissuedBlock(R), contractLine(R),
    note("이번 달 영업이익은 마감 전이라 주간 보고에 싣지 않습니다 (월간 보고에 있음)."));
  return cat(top, fund, sales);
}

// ── 월간 ────────────────────────────────────────────────────

function flowEq(R: Obj): Html {
  const s1 = R["s1"];
  const p1 = R["period"][1] as IsoDate;
  const end = p1 === monthEnd(p1) ? "월말" : md(p1);
  const cell = (lab: string, v: Html) => h("div", { class: "eq-c" }, h("span", null, lab), v);
  return h("div", { class: "eq" },
    cell("월초 잔액", money(s1["start_calc"], "R:s1.start_calc")), h("span", { class: "op" }, "+"),
    cell("입금", money(s1["in"], "R:s1.in")), h("span", { class: "op" }, "−"),
    cell("지급", money(s1["out"], "R:s1.out")), h("span", { class: "op" }, "="),
    cell(`${end} 잔액`, money(s1["end"], "R:s1.end")));
}

function pastBlock(R: Obj): Html {
  const asof = R["asof"], s5 = R["s5"];
  const po = (R["events"] as Obj[]).filter((e) => e["io"] === "out" && e["date"] && e["date"] <= asof)
    .sort((a, b) => (a["date"] < b["date"] ? -1 : a["date"] > b["date"] ? 1 : 0));
  const inMiss = s5["in_missing"]?.length;
  if (!inMiss && !s5["overdue"].length && !po.length) {
    return cat(sub("지난 미수금 · 지급 (아직 처리 안 됨)"), note("입금일 지난 미수금 없음 · 지급일 지난 출금 없음"));
  }
  const od = s5["overdue"] as Obj[];
  const odRows: Row[] = od.slice(0, 6).map((v, i) => ({ cells: [v["client"] || "", pname(R, v["project"]), md(v["due"]), `${v["overdue_days"]}일`,
    money(v["outstanding"], `R:s5.overdue.${i}.outstanding`)] }));
  if (od.length > 6) odRows.push({ cells: [`외 ${od.length - 6}건`, "", "", "", money(od.slice(6).reduce((s, v) => s + (v["outstanding"] || 0), 0), "D:overdue.rest")] });
  const poRows: Row[] = po.slice(0, 6).map((e, i) => ({ cells: [md(e["date"]), e["desc"] || "", pname(R, e["project"]), e["cat"] || "",
    money(e["amount"], `D:pastout.${i}`, "금액 미확인")] }));
  if (po.length > 6) {
    const rest = po.slice(6), known = rest.filter((e) => e["amount"] !== null && e["amount"] !== undefined);
    poRows.push({ cells: [`외 ${rest.length}건`, "", "", known.length < rest.length ? `금액 미확인 ${rest.length - known.length}건` : "",
      money(known.reduce((s, e) => s + e["amount"], 0), "D:pastout.rest")] });
  }
  return cat(sub("지난 미수금 · 지급 (아직 처리 안 됨)"),
    inMiss ? note("입금일 지난 미수금: 계산서 자료 없음", "na")
      : od.length ? table([{ t: "거래처" }, { t: "프로젝트" }, { t: "입금예정일" }, { t: "지난 날", num: true }, { t: "미수금", num: true }], odRows,
        { caption: "입금일 지난 미수금" }) : note("입금일 지난 미수금 없음"),
    po.length ? table([{ t: "예정일" }, { t: "거래처 · 내용" }, { t: "프로젝트" }, { t: "구분" }, { t: "금액", num: true }], poRows,
      { caption: "지급일 지난 출금" }) : note("지급일 지난 출금 없음"));
}

function arFig(R: Obj): Fig {
  const s5 = R["s5"];
  if (s5["in_missing"]?.length) return { label: "미수금 (세금계산서 발행 후)", value: h("span", { class: "na" }, "계산서 자료 없음") };
  if (s5["ar"] === null) return { label: "미수금 (세금계산서 발행 후)", value: h("span", { class: "na" }, `미확인 ${s5["ar_unknown_n"]}건`) };
  return { label: "미수금 (세금계산서 발행 후)", value: money(s5["ar"], "R:s5.ar"),
    foot: s5["ar_unknown_n"] ? h("span", { class: "na" }, `외 미확인 ${s5["ar_unknown_n"]}건`) : undefined };
}

function seriesTable(R: Obj): Html | null {
  const ser = monthSeries(R);
  if (ser.length < 2) return null;
  const ev = R["evid_month"] !== null && R["evid_month"] !== undefined;
  // 달이 칸 (가로): 세 줄로 짧게. 휴대폰에선 표 상자 안에서만 옆으로 밀림
  const cols: Col[] = [{ t: "" }, ...ser.map(([m]) => ({ t: ymText(m), num: true }))];
  const line = (lab: string, k: 1 | 2 | 3, f: string): Row => ({ cells: [lab, ...ser.map((x) => money(x[k], `D:series.${x[0]}.${f}`, "-"))] });
  return cat(sub(`월별 매출·매입·영업이익 (${ymText(ser[0]![0])}~${ymText(ser[ser.length - 1]![0])})`),
    table(cols, [line(ev ? "매출 (계산서)" : "매출 (손익)", 1, "sale"), ...(ev ? [line("매입 (계산서)", 2, "buy")] : []), line("영업이익", 3, "np")],
      { cls: "series" }),
    note(ev ? "매출·매입 = 세금계산서 등 증빙 작성일 기준 공급가액 · 영업이익 = 손익 기준 (공통비까지 뺀 값)"
      : "증빙월별 자료가 없어 매입은 비우고 매출은 손익 기준"));
}

function expectedBlock(R: Obj): Html {
  const E = R["s5"]["expected"];
  const y = parseInt(String(R["asof"]).slice(0, 4), 10);
  const ym = R["s4"]["ym"];
  if (!E || E["missing"]) return note("앞으로 잡힐 매출: 계산서 자료가 없어 판단 불가", "na");
  if (!E["est_n"]) return note("앞으로 잡힐 매출: 인트라넷 예상 매출(사전견적) 자료 없음", "na");
  const { ytd, key } = companyPl(R);
  const rev = ytd?.["revenue"] ?? null;
  const addv = E["past"] + E["this_year"];
  return cat(sub("올해 매출 예상", `인트라넷 예상 매출(사전견적) 기준 · 부가세 제외 · ${y + 1}년 이후 행사 제외`),
    figures([
      { label: `1월~${ymText(ym)} 누적 매출`, value: money(rev, `${key}.ytd.revenue`, "확인 필요") },
      { label: "+ 앞으로 잡힐 매출", value: money(addv, "D:expected.add"), foot: `${E["past_n"] + E["this_year_n"]}건` },
      { label: `= ${y}년 매출 예상`, value: money(rev === null ? null : rev + addv, "D:expected.total", "확인 필요") },
    ], "eqfig"));
}

const TEAM_COLS = (ytd: boolean): Col[] => [
  { t: "구분" }, { t: "매출", num: true }, { t: "매출총이익", num: true }, { t: "이익률", num: true }, { t: "급여", num: true },
  { t: "판관비", num: true }, { t: "영업이익", num: true }, { t: ytd ? "평균 인원" : "인원", num: true },
  { t: "1인당 영업이익", num: true }, { t: "공통비 나눈 뒤 1인당", num: true },
];

function teamRows(T: TeamTable, part: "cur" | "ytd", ytdAlloc: Map<string, number | null> | null): Row[] {
  const rows = part === "cur"
    ? T.rows.filter((x) => x.kind !== "other" && !(x.kind === "unlinked" && !x.revenue && !x.gp))
    : T.rows.filter((x) => x.kind === "team" || x.kind === "hq_total");
  const k = (r: TeamRow, f: string) => `D:team.${part}.${r.label}.${f}`;
  return [...rows, T.company].map((r) => {
    const costly = r.kind !== "unlinked";
    const hh = r.heads;
    const rev: Cell[] = r.has_rev ? [money(r.revenue, k(r, "revenue")), money(r.gp, k(r, "gp")), pct(r.gp, r.revenue)] : ["", "", ""];
    const per = !costly || !r.has_rev ? "" : hh === null || r.net === null || !hh ? "미확인" : money(pyRound(r.net / hh), k(r, "per"));
    let alloc: Cell = "";
    if (r.kind === "team") {
      const a = part === "cur" ? r.alloc ?? null : ytdAlloc?.get(r.label) ?? null;
      alloc = a === null || !hh ? "미확인" : money(pyRound(a / hh), k(r, "alloc"));
    }
    const heads = !costly ? "" : hh === null ? "미확인" : part === "cur" ? `${hh}명` : `${pyFixed(hh, 1)}명`;
    const label = r.kind === "company" ? cat("회사 전체", h("small", null, "인원 = 기획본부만")) : r.label;
    return {
      cls: { company: "tot", hq_total: "hq", hq_self: "mut", other: "mut", unlinked: "mut", team: "" }[r.kind],
      cells: [label, ...rev, costly ? money(r.salary, k(r, "salary")) : "", costly ? money(r.sga, k(r, "sga")) : "",
        money(r.net, k(r, "net")), heads, per, alloc],
    };
  });
}

/** 회사 손익 (이번 달 · 올해 누적) 두 칸 문서식 표 */
function companyStatement(R: Obj, Tm: TeamTable | null, Ty: TeamTable | null, depM: string, depY: string): Html {
  const ym = R["s4"]["ym"];
  const c = (T: TeamTable | null, part: string, f: string, v: (T: TeamTable) => number | null | undefined, empty = UNK) =>
    T ? money(v(T) ?? null, `D:co.${part}.${f}`, empty) : h("span", { class: "na" }, "자료 없음");
  const who = (N: Nonop, i: 1 | 2) => {
    const ps = N.by_dept.filter((d) => d[i]).map((d) => `${d[0]} ${won(d[i] as number)}`);
    return ps.length ? ` (${ps.join(" · ")})` : "";
  };
  const rows: Row[] = [
    { cells: ["매출", c(Tm, "cur", "revenue", (T) => T.company.revenue), c(Ty, "ytd", "revenue", (T) => T.company.revenue)] },
    { cells: ["매출총이익", c(Tm, "cur", "gp", (T) => T.company.gp), c(Ty, "ytd", "gp", (T) => T.company.gp)] },
    { cls: "mut", cells: ["− 급여", c(Tm, "cur", "salary", (T) => T.company.salary), c(Ty, "ytd", "salary", (T) => T.company.salary)] },
    { cls: "mut", cells: ["− 판관비", c(Tm, "cur", "sga", (T) => T.company.sga), c(Ty, "ytd", "sga", (T) => T.company.sga)] },
    { cls: "sum", cells: [cat("영업이익", h("small", null, `영업이익률 ${pct(Tm?.company.net, Tm?.company.revenue)} · 누적 ${pct(Ty?.company.net, Ty?.company.revenue)}`)),
      c(Tm, "cur", "net", (T) => T.company.net, "확인 필요"), c(Ty, "ytd", "net", (T) => T.company.net, "확인 필요")] },
    { cls: "mut", cells: [`+ 영업외 수익${Tm ? who(Tm.nonop, 1) : ""}`, c(Tm, "cur", "nonop_in", (T) => T.nonop.in), c(Ty, "ytd", "nonop_in", (T) => T.nonop.in)] },
    { cls: "mut", cells: [`− 영업외 비용${Tm ? who(Tm.nonop, 2) : ""}`, c(Tm, "cur", "nonop_out", (T) => T.nonop.out), c(Ty, "ytd", "nonop_out", (T) => T.nonop.out)] },
  ];
  if ((Tm && Tm.nonop.dep !== undefined) || (Ty && Ty.nonop.dep !== undefined)) {
    rows.push({ cls: "mut", cells: [`− 감가상각비 (예상${depY || depM})`, c(Tm, "cur", "dep", (T) => T.nonop.dep), c(Ty, "ytd", "dep", (T) => T.nonop.dep)] });
  }
  rows.push({ cls: "tot", cells: ["세전 이익", c(Tm, "cur", "pretax", (T) => T.nonop.pretax, "확인 필요"), c(Ty, "ytd", "pretax", (T) => T.nonop.pretax, "확인 필요")] });
  return table([{ t: "" }, { t: `${ymText(ym)}`, num: true, sub: "마감 전" }, { t: `1월~${ymText(ym)}`, num: true }], rows, { cls: "stmt" });
}
const UNK = "미확인";

function targetTable(R: Obj, Y: TeamTable, ym: string): Html {
  const T = (R["targets"] || {}) as Obj;
  const teams = Y.rows.filter((r) => r.kind === "team");
  const mon = parseInt(ym.slice(5, 7), 10), pace = mon / 12;
  let sumT = 0, sumR = 0, allT = true, sumG = 0, gKnown = true;
  const rows: Row[] = teams.map((r) => {
    const t = (T[r.label] || {}) as Obj;
    const tr = t["revenue"] ?? null, rate = t["rate"] ?? null;
    const actRate = !r.revenue || r.gp === null ? null : (r.gp * 100) / r.revenue;
    if (r.gp === null) gKnown = false; else sumG += r.gp;
    let ach: number | null = null;
    let achTxt: Child;
    if (tr && r.revenue !== null) {
      ach = r.revenue / tr; sumT += tr; sumR += r.revenue;
      achTxt = `${pyFixed(ach * 100, 1)}%`;
    } else {
      allT = false;
      achTxt = h("span", { class: "na" }, !tr ? "목표 없음" : "미확인");
    }
    const verdict: string[] = [];
    if (ach !== null) verdict.push(ach >= pace ? "목표 이상" : "목표 미달");
    if (rate !== null && actRate !== null) verdict.push(actRate >= rate ? "수익률 달성" : "수익률 미달");
    return { cells: [r.label, money(tr, `R:targets.${r.label}.revenue`, "목표 없음"), money(r.revenue, `D:team.ytd.${r.label}.revenue`), achTxt,
      money(r.gp, `D:team.ytd.${r.label}.gp`),
      `${actRate === null ? "—" : pyFixed(actRate, 1) + "%"} / ${rate === null ? "—" : String(rate).replace(/\.0$/, "") + "%"}`,
      verdict.join(" · ") || "—"] };
  });
  const total = teams.length && allT && sumT
    ? ["팀 합계", money(sumT, "D:target.sum_t"), money(sumR, "D:target.sum_r"), `${pyFixed((sumR * 100) / sumT, 1)}%`,
      money(gKnown ? sumG : null, "D:target.sum_g"), gKnown && sumR ? `${pyFixed((sumG * 100) / sumR, 1)}%` : "", ""] : undefined;
  if (!Object.keys(T).length) return note("팀 목표 없음 — 대표보고 창 '⑧ 팀 목표'에 연간 매출 목표와 목표 수익률을 넣으면 보입니다");
  return cat(sub("팀별 목표 대비", `진도 기준 ${mon}월/12 = ${pyFixed(pace * 100, 0)}%`),
    table([{ t: "팀" }, { t: "연간 매출 목표", num: true }, { t: "누적 매출", num: true }, { t: "달성률", num: true },
      { t: "누적 매출총이익", num: true }, { t: "수익률", num: true, sub: "실제 / 목표" }, { t: "판정" }], rows, { total }),
    Object.keys(T).length ? null : note("팀 목표 없음 — 대표보고 창 '⑧ 팀 목표'에 연간 매출 목표와 목표 수익률을 넣으면 보입니다"));
}

function monthly(R: Obj): Html {
  const s1 = R["s1"];
  const ym = R["s4"]["ym"] as string;
  const p1 = R["period"][1] as IsoDate;
  const endLab = p1 === monthEnd(p1) ? `${ymText(ym)}말` : `${md(p1)} 현재`;
  const upto = p1 === monthEnd(p1) ? "" : ` (${md(p1)}까지)`;
  const np = monthNp(R);
  const top = figures([
    { label: `${endLab} 쓸 수 있는 돈`, value: money(s1["available"], "R:s1.available"),
      foot: s1["available"] !== null && s1["restricted"] ? cat("통장 ", money(s1["total"], "R:s1.total"), " − 담보·전용 ",
        money(s1["restricted"], "R:s1.restricted")) : undefined },
    availFig(R, "last"),
    { label: `${ymText(ym)} 영업이익${upto}`, value: money(np, "D:co.cur.net", "확인 필요"), foot: "마감 전" },
    overdueFig(R),
  ].filter(Boolean) as Fig[], "top");
  const fund = section(1, "자금 흐름",
    sub(`이번 달 자금 흐름`, "계좌 간 이체 제외"), flowEq(R),
    availTable(R), balanceSection(R, "monthly"), pastBlock(R));
  const { cur, src, key } = companyPl(R);
  const sales = section(2, `${ymText(ym)} 매출·매입`,
    figures([
      cur ? { label: `${ymText(ym)} 매출`, value: money(cur["revenue"], `${key}.cur.revenue`),
        foot: cat("매출총이익 ", money(cur["gp"], `${key}.cur.gp`), ` (${pct(cur["gp"], cur["revenue"])})`) }
        : { label: `${ymText(ym)} 매출`, value: h("span", { class: "na" }, src ? `자료 없음 (최근 ${src["latest"] || "-"})` : "자료 없음") },
      buyFig(R, ym), arFig(R), unissuedFig(R),
    ]),
    unissuedBlock(R), seriesTable(R), expectedBlock(R), contractLine(R));
  // 회사 수익 · 팀별 수익
  const dept = R["s4"]["dept"] ?? null;
  const hasTeams = src && (src["table"] as Obj[]).some((r) => r["unit"] !== "회사");
  const Tm = src ? teamBuild(src["table"], dept, ym, false) : null;
  const Ty = src ? teamBuild(src["table"], dept, ym, true) : null;
  const depM = Tm ? depInto(R, Tm, false) : "";
  const depY = Ty ? depInto(R, Ty, true) : "";
  if (Tm) teamAllocate(Tm);
  if (Ty) teamAllocate(Ty);
  const profit = section(3, "회사 수익", companyStatement(R, Tm, Ty, depM, depY),
    note("영업이익 = 매출총이익 − 모든 부서 급여·판관비 (분개장 부서명 기준) · 세전 이익 = 영업이익 + 영업외 수익 − 영업외 비용"),
    !Tm?.dept_ok ? warn(dept === null ? `급여·판관비 미확인: ${R["s4"]["dept_problem"] ? "부서비용.csv " + R["s4"]["dept_problem"] : "부서비용.csv 없음"}`
      : `급여·판관비 미확인: 부서비용.csv에 ${ymText(ym)} 자료가 없음`) : null,
    note("법인세·당기순이익 예상과 부가세·원천세 일정은 경영관리 보고에 있습니다."));
  const ytdAlloc = Ty && src ? teamYtdAlloc((src["by_month"] || []) as [string, Obj[]][], dept) : null;
  const team = section(4, "팀별 수익",
    !hasTeams ? warn("팀별 자료 없음 (인트라넷 프로젝트 목록이 있어야 팀으로 묶음)") : cat(
      Tm ? cat(sub(`${ymText(ym)}`, "마감 전"), table(TEAM_COLS(false), teamRows(Tm, "cur", null), { cls: "team" })) : null,
      ym.endsWith("-01") ? note("1월은 올해 누적이 이번 달과 같아 누적 표를 따로 싣지 않습니다.")
        : Ty ? cat(sub(`1월~${ymText(ym)} 누적`), table(TEAM_COLS(true), teamRows(Ty, "ytd", ytdAlloc), { cls: "team" })) : warn("올해 누적 자료 없음"),
      note("영업이익 = 매출총이익 − 그 팀 급여·판관비. 본부 비용은 본부 합계에서 뺌 · 공통비 나눈 뒤 = 본부·경영관리 등 비용을 팀 인원 비율로 나눠 뺀 값"),
      Ty ? targetTable(R, Ty, ym) : null));
  return cat(top, fund, sales, profit, team);
}

// ── 바깥 ────────────────────────────────────────────────────

/** 막는 까닭 화면 (gate.stop_page 의 대표판 글). */
export function stopHtml(stop: string[], title = "보고"): Html {
  return h("article", { class: "report stop" },
    h("h1", null, `${title} — 만들지 않음`),
    h("div", { class: "gate", role: "alert" },
      h("p", null, "자금계획서·분개장이 반영되지 않아 이 보고를 만들지 않았습니다"),
      h("ul", null, stop.map((p) => h("li", null, p)))),
    h("p", null, "위하고 확장으로 분개장과 자금계획서를 받은 뒤 자료 변환을 다시 하면 만들어집니다."));
}

export function reportHtml(R: Obj, kind: ReportKind, opts: ReportOpts = {}): Html {
  const title = `${(R?.["settings"] || {})["회사명"] || ""} ${kind === "weekly" ? "주간" : "월간"} 보고`.trim();
  if (opts.stop && opts.stop.length) return stopHtml(opts.stop, title);
  const lag = bankLagNote(R);
  return h("article", { class: `report ${kind}` },
    header(R, kind, opts.made),
    R["plan_gap_note"] ? warn(R["plan_gap_note"]) : null,
    lag ? warn(lag) : null,
    kind === "weekly" ? weekly(R) : monthly(R),
    h("p", { class: "doc-end" }, "끝."));
}

function toElement(x: Html): HTMLElement {
  const t = document.createElement("template");
  t.innerHTML = x.s;
  return t.content.firstElementChild as HTMLElement;
}

/** 대표 보고 화면. stop 을 주고 비어 있지 않으면 보고 대신 까닭만. */
export function renderReport(R: Obj, kind: ReportKind, opts: ReportOpts = {}): HTMLElement {
  return toElement(reportHtml(R, kind, opts));
}

export function renderStop(stop: string[], title?: string): HTMLElement {
  return toElement(stopHtml(stop, title));
}
