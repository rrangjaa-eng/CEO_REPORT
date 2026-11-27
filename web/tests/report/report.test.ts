// 대표 보고 화면: 보이는 숫자 칸마다 R 의 값과 1원까지 같은지, 모르는 값이 0 이 아니라 '미확인'인지, 막힌 보고는 까닭만 보이는지.
// 숫자 칸은 모두 <span class="m" data-k="출처" data-v="값">글자</span> 꼴이다 (fmt.money).
//   R:경로  → R 의 그 자리 값과 비교 (자동)
//   D:이름  → 화면 직전 계산값: 아래에서 R 로 따로 다시 계산하거나, 파이썬 대표 보고(render.py)가 낸 글자와 비교
import { describe, expect, it } from "vitest";
import { loadCase } from "../calc/golden";
import { loadData } from "../../src/model/data";
import { buildReport } from "../../src/calc/report";
import { won } from "../../src/model/util";
import { withVat } from "../../src/calc/projects";
import { reportHtml, type ReportKind } from "../../src/report/report";

type Obj = Record<string, any>;
interface Num { k: string; v: number | null; text: string }

const UNKNOWN_WORDS = ["미확인", "확인 필요", "잔액 미확인", "자료 없음", "금액 미확인", "목표 없음", "-"];

function nums(html: string): Num[] {
  const out: Num[] = [];
  const re = /<span class="m[^"]*" data-k="([^"]+)"(?: data-v="([^"]*)")?>([^<]*)<\/span>/g;
  for (const m of html.matchAll(re)) out.push({ k: m[1]!, v: m[2] ? Number(m[2]) : null, text: m[3]! });
  return out;
}

function at(R: Obj, path: string): unknown {
  let x: any = R;
  for (const p of path.split(".")) {
    if (x === null || x === undefined) return undefined;
    x = x[/^\d+$/.test(p) && Array.isArray(x) ? Number(p) : p];
  }
  return x;
}

const cache = new Map<string, { R: Obj; stop: string[]; html: string }>();
function run(id: string, kind: ReportKind) {
  const key = `${id}/${kind}`;
  if (!cache.has(key)) {
    const c = loadCase(id);
    const { R, stop } = buildReport(loadData(c.files), c.files, kind, c.case.asof, c.case.payday ?? null);
    cache.set(key, { R, stop, html: reportHtml(R, kind, { stop }).s });
  }
  return cache.get(key)!;
}

const REPORTS: [string, ReportKind][] = [
  ["base", "weekly"], ["base", "monthly"], ["u_unknown_not_zero", "weekly"], ["u_year_change", "weekly"], ["u_year_change", "monthly"],
  ["d_card_vendor", "weekly"], ["f_must_pay", "weekly"], ["u_transfer", "weekly"], ["u_book_balance", "weekly"],
];
const STOPPED: [string, ReportKind][] = [["u_no_fundplan", "weekly"], ["u_journal_8days", "weekly"], ["f_tax_missing", "weekly"], ["u_other_company", "weekly"]];

describe.each(REPORTS)("%s %s", (id, kind) => {
  it("막히지 않은 사례", () => expect(run(id, kind).stop).toEqual([]));

  it("숫자 칸 글자 = 값 (천 단위 쉼표, 음수 '−'), 모르는 값은 0 이 아니라 미확인", () => {
    const ns = nums(run(id, kind).html);
    expect(ns.length).toBeGreaterThan(20);
    for (const n of ns) {
      if (n.v === null) expect(UNKNOWN_WORDS, n.k).toContain(n.text);
      else expect(n.text, n.k).toBe(won(n.v));
      expect(n.text, n.k).not.toMatch(/-\d/);   // 빼기표는 늘 U+2212
    }
  });

  it("R: 숫자 칸 = R 의 값 (1원까지)", () => {
    const { R, html } = run(id, kind);
    const rs = nums(html).filter((n) => n.k.startsWith("R:"));
    expect(rs.length).toBeGreaterThan(8);
    for (const n of rs) {
      const want = at(R, n.k.slice(2));
      expect(want, `${n.k} 이 R 에 없음`).not.toBeUndefined();
      expect(n.v, n.k).toBe(want === null ? null : want);
    }
  });

  it("D: 숫자 칸을 R 로 따로 다시 계산해 맞춤", () => {
    const { R, html } = run(id, kind);
    const ns = nums(html);
    const get = (k: string) => ns.filter((n) => n.k === k);
    const one = (k: string) => { const g = get(k); expect(g.length, k).toBeGreaterThan(0); return g[0]!.v; };
    const s2 = R["s2"];
    // 기간별 여유 자금의 '예상 별도' = all − firm
    for (const n of ns.filter((n) => /^D:s2\.periods\.\d+\.(in|out)_extra$/.test(n.k))) {
      const [, i, io] = /periods\.(\d+)\.(in|out)_extra/.exec(n.k)!;
      const p = s2["periods"][Number(i)];
      const f = io === "in" ? "pin" : "pout";
      expect(n.v, n.k).toBe(p["all"][f] - p["firm"][f]);
    }
    // 행사 후 미발행: 줄마다 부가세 포함, 합계 = 줄 합
    const E = R["s5"]["event_unissued"];
    if (!E["missing"] && E["rows"].length) {
      E["rows"].forEach((y: Obj, i: number) => expect(one(`D:unissued.${i}`)).toBe(withVat(y["unissued"])));
      expect(one("D:unissued.total")).toBe(E["rows"].reduce((s: number, y: Obj) => s + withVat(y["unissued"]), 0));
    }
    if (kind === "weekly") {
      // 출금일 목록 합계 = 줄 합 = R.events 중 (기준일 뒤 ~ 출금일, 확정·금액 있음, 장부 미확인 아님)
      const rows = ns.filter((n) => /^D:week\.pay\.\d+$/.test(n.k));
      const total = one("D:week.pay.total");
      expect(total).toBe(rows.reduce((s, n) => s + (n.v ?? 0), 0));
      const fri = R["payday"];
      const want = (R["events"] as Obj[]).filter((e) => e["io"] === "out" && e["date"] && e["date"] <= fri
        && !(e["date"] <= R["asof"] && e["date"] < fri) && e["firm"] && e["amount"] !== null && !e["gap"] && e["source"] !== "남은 예산");
      expect(total).toBe(want.reduce((s, e) => s + e["amount"], 0));
      expect(rows.length).toBe(want.length);
      // 다음 주: 합계 = 금액 아는 것의 합
      const end = new Date(Date.parse(fri) + 7 * 864e5).toISOString().slice(0, 10);
      const nx = (R["events"] as Obj[]).filter((e) => e["io"] === "out" && e["date"] > fri && e["date"] <= end && !e["gap"]);
      if (nx.length) expect(one("D:week.next.total")).toBe(nx.reduce((s, e) => s + (e["amount"] ?? 0), 0));
      // 매입: 증빙월별 그 달 줄 (없으면 0)
      const ev = R["evid_month"];
      const b = ns.find((n) => n.k === `R:evid_month.${R["s4"]["ym"]}.1` || n.k === "D:buy.none")!;
      expect(b.v).toBe(ev === null ? null : (ev[R["s4"]["ym"]] ?? [0, 0])[1]);
    } else {
      for (const [m, pair] of Object.entries((R["evid_month"] || {}) as Record<string, [number, number]>)) {
        if (m.slice(0, 4) !== R["s4"]["ym"].slice(0, 4) || m > R["s4"]["ym"]) continue;
        expect(one(`D:series.${m}.sale`)).toBe(pair[0]);
        expect(one(`D:series.${m}.buy`)).toBe(pair[1]);
      }
      // 회사 손익: 영업이익 = 매출총이익 − 급여 − 판관비, 세전 = 영업이익 + 영업외 수익 − 영업외 비용 (− 감가상각비)
      for (const part of ["cur", "ytd"]) {
        const v = (f: string) => one(`D:co.${part}.${f}`);
        if (v("gp") !== null && v("salary") !== null && v("sga") !== null) expect(v("net")).toBe(v("gp")! - v("salary")! - v("sga")!);
        const dep = get(`D:co.${part}.dep`)[0]?.v ?? 0;
        if (v("net") !== null && v("nonop_in") !== null && v("nonop_out") !== null) {
          expect(v("pretax")).toBe(v("net")! + v("nonop_in")! - v("nonop_out")! - dep);
        }
      }
      expect(one("D:co.cur.revenue")).toBe(at(R, "s4.sources.WEHAGO.table.0.cur.revenue"));
    }
  });
});

describe("파이썬 대표 보고(render.py)와 같은 숫자 — base", () => {
  it("주간: 출금 목록 · 다음 주 · 지난주 대비 · 미발행", () => {
    const { html } = run("base", "weekly");
    const t = html.replace(/<[^>]+>/g, "");
    for (const s of ["11/06(금) 출금", "166,200,000", "82,938,235", "27,338,235", "266,200,000", "196,600,000", "238,861,765", "22,447,060",
      "지난주 대비: 지난주(10/24~10/30) 출금 24,500,000 → 이번 출금 166,200,000 (+141,700,000) · 빠진 것 3건 −24,500,000 · 추가된 것 2건 +166,200,000 · 카드·세금 자동 출금은 빼고 비교",
      "181,500,000", "88,000,000", "1,164,000,000", "[26220] 가상 전시", "계약금액이 없어 지금 예상 이익을 못 낸 프로젝트 3개"]) {
      expect(t, s).toContain(s);
    }
  });
  it("월간: 흐름 · 팀 표 · 결산 · 목표 · 올해 매출 예상", () => {
    const t = run("base", "monthly").html.replace(/<[^>]+>/g, "|");
    for (const s of ["574,600,000", "2,200,000", "572,400,000", "542,400,000", "−20,400,000", "103,400,000", "77,500,000", "−234,705,880",
      // 이번 달 팀 표 (파이썬과 같은 줄)
      "16,500,000", "5,280,000", "−5,720,000", "−1,906,667", "−3,573,333", "−4,680,000", "−1,560,000", "−3,226,667", "−15,400,000", "−2,200,000", "−2,914,286",
      // 누적 팀 표
      "533,500,000", "170,720,000", "71,720,000", "29,219,259", "10,885,926", "23,906,667", "5,573,333", "85,400,000", "14,911,111", "−31,600,000", "−5,517,460",
      // 결산
      "−18,900,000", "−18,500,000", "18,000,000", "4,900,000", "영업외 수익 (경영관리 2,000,000)", "영업외 비용 (기획본부 500,000)",
      // 목표 · 매출 예상
      "900,000,000", "59.3%", "62.4%", "1,600,000,000", "60.6%", "730,000,000", "1,894,000,000", "248,400,000"]) {
      expect(t, s).toContain(s);
    }
  });
});

describe("모르는 값은 0 이 아님 — u_unknown_not_zero", () => {
  it("다음 주 지급에 금액 미확인 1건이 따로 보이고 합계에 0 으로 들어가지 않음", () => {
    const t = run("u_unknown_not_zero", "weekly").html.replace(/<[^>]+>/g, "|");
    expect(t).toContain("미확인 1건");
    expect(t).toContain("+ 금액 미확인 1건");
    expect(t).toContain("82,938,235");   // 파이썬도 같은 합계 (미확인 줄은 빼고)
  });
});

describe.each(STOPPED)("막힌 보고 %s %s", (id, kind) => {
  it("보고 대신 까닭만", () => {
    const { stop, html } = run(id, kind);
    expect(stop.length).toBeGreaterThan(0);
    expect(html).toContain("만들지 않음");
    for (const p of stop) expect(html).toContain(p.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;"));
    expect(nums(html)).toEqual([]);   // 숫자는 하나도 보이지 않음
  });
});
