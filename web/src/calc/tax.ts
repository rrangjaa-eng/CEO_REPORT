// 세금 예상을 자금 일정에 넣는다 — 파이썬 ceo_report/tax.py merge (965-1076).
// 바꿀 것 U6: 거래처코드 비교는 양쪽 같은 규칙(codeKey: 숫자가 아닌 코드도 앞 0을 뗌).
import { daysBetween, type IsoDate } from "../model/dates";
import { cmpStr, fmtComma, PY_SPACE } from "../model/py";
import { RULES } from "../model/rules";
import { codeKey, nextFriday, type FundEvent } from "./fundplan";

/** data.load 의 d.tax 한 줄 (세금예상.csv). codes 는 파이썬 튜플 → 목록. */
export interface TaxRow {
  kind: string;
  period: string;
  due: IsoDate | null;
  amount: number | null;
  state: string;
  basis: string;
  codes: string[];
  book: IsoDate | null;
  base?: number | null;
  calc?: number | null;
  prepaid?: number | null;
  [k: string]: unknown;
}

/** 세금 줄 + 맞춘 일정 (파이썬 dict(t, matched=…, matched_all=…, diff=…, by_name=…, moved=…)). */
export interface TaxInfo extends TaxRow {
  matched: FundEvent | { merged_card: true; amount: null } | null;
  matched_all: FundEvent[];
  diff: number | null;
  by_name: boolean;
  moved: string;
}

export const DEPOSIT_IN = "정기예금 만기";
export const DEPOSIT_OUT = "정기예금 가입";
export const KEYWORDS: Record<string, readonly string[]> = {
  부가세: ["부가"], 원천세: ["원천", "소득세", "지방소득"],
  "4대보험": ["4대보험", "사대보험", "국민연금", "건강보험", "고용보험", "산재", "근로복지", "공단"],
  급여: ["급여", "월급", "임금", "인건비"], 카드대금: ["카드"], [DEPOSIT_IN]: ["정기예금", "예금"],
  [DEPOSIT_OUT]: ["정기예금", "예금"], 법인세: ["법인세"], 법인지방소득세: ["법인지방소득세", "법인지방"],
};
export const OFFICE: Record<string, readonly string[]> = {
  부가세: ["세무서"], 원천세: ["세무서", "구청", "시청", "군청"], 법인세: ["세무서"], 법인지방소득세: ["구청", "시청", "군청"] };
export const NEAR_DAYS = 7;
export const NOT_TAX = ["남은 예산", "프로젝트집행", "계산서"];
export const GAP_KINDS = ["부가세", "원천세", "법인세", "법인지방소득세"];

const SPACES = new RegExp("[" + PY_SPACE + "]+", "g");
const STRIP = new RegExp("^[" + PY_SPACE + "]+|[" + PY_SPACE + "]+$", "g");
const sq = (text: unknown) => pyStr(text).replace(SPACES, "");
/** 파이썬 str(x or "") */
function pyStr(x: unknown): string {
  if (x === null || x === undefined || x === "" || x === 0 || x === false) return "";
  if (x === true) return "True";
  return String(x);
}
const ioOf = (t: TaxRow) => (t.kind === DEPOSIT_IN ? "in" : "out");
const cardCo = (t: TaxRow) => pyStr(t.period).split("카드")[0]!.replace(STRIP, "");

/** 세금 예상을 일정에 넣는다. 이미 일정에 같은 세금이 있으면 넣지 않고 비교만. -> [새 일정, 세금 줄마다 설명]. */
export function mergeTax(
  events: FundEvent[], taxes: TaxRow[] | null | undefined, asof: IsoDate | null = null, cashDate: IsoDate | null = null,
): [FundEvent[], TaxInfo[]] {
  const out = [...events];
  const tx = [...(taxes || [])];
  const found: (FundEvent[] | null)[] = tx.map(() => null);
  const byName: boolean[] = tx.map(() => false);
  const taken = new Set<number>();

  const near = (ev: FundEvent, t: TaxRow) => {
    if (t.due === null) return false;
    const day = ev.orig_date || ev.date;
    return ev.io === ioOf(t) && !!day && Math.abs(daysBetween(t.due, day)) <= NEAR_DAYS;
  };
  /** 고침(RULES.taxSameMonth): 세목 낱말로 맞출 때는 납부일과 같은 달이어도 같은 세금으로 본다.
   * 단 그 일정이 다른 세금 줄의 납부일 ±7일 안이면 그쪽 것이므로 가져오지 않는다. 거래처코드·금액으로 맞출 때는 ±7일 그대로
   * (세무서 코드는 여러 세목이 같이 쓴다). */
  const nearKind = (ev: FundEvent, t: TaxRow) => {
    if (near(ev, t)) return true;
    if (!RULES.taxSameMonth || t.due === null || ev.io !== ioOf(t)) return false;
    const day = ev.orig_date || ev.date;
    return !!day && day.slice(0, 7) === t.due.slice(0, 7) && !tx.some((o) => o !== t && near(ev, o));
  };
  const codes = (t: TaxRow) => new Set((t.codes || []).map(codeKey));   // U6
  const evCode = (ev: FundEvent) => codeKey(ev.vendor_code);
  const conflict = (ev: FundEvent, t: TaxRow) => {
    const c = evCode(ev), cs = codes(t);
    return !!c && cs.size > 0 && !cs.has(c);
  };
  const text = (ev: FundEvent) => sq(["cat", "desc", "basis"].map((k) => pyStr(ev[k])).join(" "));
  const words = (t: TaxRow): readonly string[] => {
    if (t.kind === "카드대금") {
      const co = cardCo(t);
      return co ? [co] : [];
    }
    return KEYWORDS[t.kind] || [];
  };
  const usable = (i: number, ev: FundEvent) => !taken.has(i) && !NOT_TAX.includes(ev.source as string);

  tx.forEach((t, n) => {
    const cs = codes(t);
    if (!cs.size) return;
    const hit: number[] = [];
    events.forEach((ev, i) => {
      if (usable(i, ev) && near(ev, t) && cs.has(evCode(ev))) hit.push(i);
    });
    if (hit.length) {
      found[n] = hit.map((i) => events[i]!);
      for (const i of hit) taken.add(i);
    }
  });
  const tests: ((ev: FundEvent, t: TaxRow) => boolean)[] = [
    (ev, t) => words(t).some((w) => text(ev).includes(w)),
    (ev, t) => (OFFICE[t.kind] || []).some((w) => text(ev).includes(w)),
    (ev, t) => t.amount !== null && ev.amount === t.amount,
  ];
  tests.forEach((test, k) => {
    const close = k < 2 ? nearKind : near;
    tx.forEach((t, n) => {
      if (found[n] !== null) return;
      for (let i = 0; i < events.length; i++) {
        const ev = events[i]!;
        if (usable(i, ev) && close(ev, t) && !conflict(ev, t) && test(ev, t)) {
          found[n] = [ev];
          byName[n] = true;
          taken.add(i);
          break;
        }
      }
    });
  });
  const cardKey = (t: TaxRow) => JSON.stringify([cardCo(t), t.due]);
  const cardHit = new Set<string>();
  tx.forEach((t, n) => {
    if (found[n] !== null && t.kind === "카드대금") cardHit.add(cardKey(t));
  });
  const info: TaxInfo[] = [];
  tx.forEach((t, n) => {
    const hits = found[n] ?? null;
    if (hits === null && t.kind === "카드대금" && cardHit.has(cardKey(t))) {
      info.push({ ...t, matched: { merged_card: true, amount: null }, matched_all: [], diff: null, by_name: false, moved: "" });
      return;
    }
    const match = hits && hits.length ? hits[0]! : null;
    const amounts = (hits || []).map((ev) => ev.amount);
    const got = !hits || !hits.length || amounts.some((a) => a === null) ? null : amounts.reduce((s: number, a) => s + (a as number), 0);
    const diff = got === null || t.amount === null ? null : got - t.amount;
    const row: TaxInfo = { ...t, matched: match, matched_all: [...(hits || [])], diff, by_name: byName[n]!, moved: "" };
    info.push(row);
    if (diff !== null && diff < 0 && t.due !== null && GAP_KINDS.includes(t.kind)) {
      out.push({ date: match!.date, io: ioOf(t), amount: -diff, firm: false,
        cat: `${t.kind} (장부 계산 차액)`, desc: `${t.kind} ${t.period}`,
        basis: `장부 계산 ${fmtComma(t.amount as number)}원 − 일정 ${fmtComma(got as number)}원`,
        project: "", source: "세금예상", tax_gap: true });
    }
    if (match === null && t.due !== null && (t.amount === null || t.amount > 0)) {
      const ev: FundEvent = { date: t.due, io: ioOf(t), amount: t.amount, firm: t.state.startsWith("확정"),
        cat: `${t.kind} (장부 계산)`, desc: `${t.kind} ${t.period}`, basis: t.basis,
        project: "", source: "세금예상", vendor_code: [...new Set(t.codes || [])].sort(cmpStr).join(" ") };
      if (asof !== null && t.due <= asof) {
        const book = t.book ?? null;
        let why: string;
        if (book !== null && book >= t.due) {
          why = `납부일 ${t.due} 지남, 장부(${book}까지)에 ${ioOf(t) === "in" ? "입금" : "납부"} 없음 → 다음 금요일`;
        } else if (cashDate !== null && cashDate >= t.due) {
          row.moved = `납부일 ${t.due}이 통장 잔액 기준일 ${cashDate} 이전 → 잔액에 이미 반영된 것으로 봄 (장부는 ${book ? book : "날짜 모름"}까지)`;
          return;
        } else {
          why = `납부일 ${t.due} 지남, 장부가 ${book ? book : "언제"}까지만 있어 냈는지 모름 → 다음 금요일 (이미 나갔으면 빼도 됨)`;
          ev.gap = t.due;
        }
        ev.date = nextFriday(asof);
        ev.orig_date = t.due;
        ev.basis = (ev.basis ? ev.basis + ", " : "") + why;
        row.moved = why;
      }
      out.push(ev);
    }
  });
  return [out, info];
}
