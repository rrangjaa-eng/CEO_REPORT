// convert.py 의 표 만들기: 증빙월별·장부채무·장부잔액/입출금·세금예상·자금계획(받은달)·장부알림, 이전 파일 읽기.
import { BOOK_BAL_FILE, BOOK_BAL_KEYS, BOOK_NOTE_FILE, BOOK_NOTE_KEYS, BOOK_TXN_FILE, EVID_FILE, EVID_KEYS, FUNDPLAN_RECEIVED_FILE,
  SCHEMA, TRANSFER } from "../model/data";
import type { IsoDate } from "../model/dates";
import { addDays, daysBetween, monthEnd, ymd } from "../model/dates";
import { cmpStr, fmtComma, pyStrip, sortedBy } from "../model/py";
import { Issues, rget, won } from "../model/util";
import { normCode, normVendor } from "../model/vendor";
import type { Cfg } from "./config";
import { carryRows, fromJournal, readManual, type Law } from "./corptax";
import { exists, join, readCsvFile, type ConvFiles } from "./files";
import * as fundplan from "./fundplan";
import { cardUsage, compareScreens, rawFiles } from "./screens";
import { Table, type TRow } from "./table";
import * as tax from "./tax";
import { journalFromStart, squash, type Books, type JLine, type Sales } from "./wehago";

const FUNDPLAN_RECEIVED_KEYS = ["대상월", "자료일", "파일"];
const fmt = fmtComma;

/** _read_prev_state: [줄, '없음' | 'ok' | '읽지 못함'] */
export function readPrevState(files: ConvFiles, inputDir: string, name: string): [TRow[], string] {
  const cols = SCHEMA[name];
  const path = join(inputDir, name);
  if (cols === undefined || !exists(files, path)) return [[], "없음"];
  const info: { missing?: string[] } = {};
  const [rows, ok] = readCsvFile(files, path, cols, new Issues(), info);
  if (!ok || (info.missing && info.missing.length)) return [[], "읽지 못함"];
  return [rows.map((r) => {
    const o: TRow = {};
    for (const [k, v] of Object.entries(r)) if (k !== "_line" && k !== "_file" && k !== "_overflow") o[k] = v as string;
    return o;
  }), "ok"];
}

/** _read_prev_rows: 없으면 [], 읽지 못하면 null */
export function readPrevRows(files: ConvFiles, inputDir: string, name: string, keys: readonly string[], extra: readonly string[] = []): TRow[] | null {
  const path = join(inputDir, name);
  if (!exists(files, path)) return [];
  const info: { missing?: string[] } = {};
  const [rows, ok] = readCsvFile(files, path, keys, new Issues(), info);
  if (!ok || (info.missing && info.missing.length)) return null;
  return rows.map((r) => {
    const o: TRow = {};
    for (const k of [...keys, ...extra]) o[k] = rget(r, k) ?? "";
    return o;
  });
}

export function keepIfUnreadable(table: Table, prev: TRow[] | null): Table {
  if (prev === null && table.written) {
    table.written = false;
    table.reason = `이전 ${table.name} 를 읽지 못해 그대로 둠 (새 장부에 없는 지난 달을 잃지 않게) — 엑셀에서 열려 있으면 닫고, 깨졌으면 파일을 다른 이름으로 옮긴 뒤 다시 변환하세요`;
  }
  return table;
}

/** build_evidence */
export function buildEvidence(books: Books, sales: Sales, prevRows: TRow[] = []): Table {
  const cells = new Map<string, [[number, number], [number, number]]>();
  const add = (rows: { date: IsoDate | null; supply: number | null }[], i: 0 | 1) => {
    for (const r of rows) {
      if (r.date === null) continue;
      const ym = r.date.slice(0, 7);
      if (!cells.has(ym)) cells.set(ym, [[0, 0], [0, 0]]);
      const c = cells.get(ym)![i];
      if (r.supply === null) c[1]++;
      else c[0] += r.supply;
    }
  };
  const haveSales = sales.state === "ok", haveBuys = books.state === "ok";
  if (haveSales) add(sales.rows, 0);
  if (haveBuys) add(books.ledger, 1);
  if (!cells.size) return new Table(EVID_FILE, EVID_KEYS, [], { written: false, reason: "매출·매입 증빙 자료 없음 (기존 파일 그대로)" });
  const cell = (c: [number, number], ok: boolean) => (!ok || c[1] ? "" : String(Math.trunc(c[0])));
  let rows: TRow[] = prevRows.filter((r) => !cells.has(String(r["연월"] ?? "")));
  for (const [ym, [sv, bv]] of cells) rows.push({ "연월": ym, "매출": cell(sv, haveSales), "매입": cell(bv, haveBuys) });
  rows = sortedBy(rows, (r) => String(r["연월"] ?? ""));
  const note = `매출 ${haveSales ? sales.source || "자료 없음" : "자료 없음"} · 매입 ${haveBuys ? (books.from_journal ? "분개장 매입전표" : "매입매출장 매입") : "자료 없음"} · 작성일자(전표일자) 달별 공급가액`;
  return new Table(EVID_FILE, EVID_KEYS, rows, { notes: [note] });
}

// ───────────── debts.build ─────────────
export const DEBT_FILE = "장부채무.csv";
export const DEBT_KEYS = ["구분", "계정코드", "계정과목", "거래처코드", "거래처", "잔액", "기준일", "만기일", "만기근거", "전기이월"];
const PAYABLE = "미지급금", LOAN = "차입금", DEPOSIT = "정기예금";
const DATE_RE = /(20\p{Nd}{2})\s*[.\-/년]\s*(\p{Nd}{1,2})\s*[.\-/월]\s*(\p{Nd}{1,2})/gu;

function memoDate(memo: string): IsoDate | null {
  const text = memo || "";
  const pos = text.indexOf("만기");
  const cands = [...(pos >= 0 ? text.slice(pos) : text).matchAll(DATE_RE)];
  for (const m of pos >= 0 ? cands : cands.reverse()) {
    try {
      return ymd(Number(m[1]), Number(m[2]), Number(m[3]));
    } catch {
      continue;
    }
  }
  return null;
}

const isOpening = (ln: JLine) => {
  const memo = squash(ln.memo);
  return memo.includes("전기이월") || memo.includes("기초잔액");
};

export function buildDebts(books: Books, cfg: Cfg): Table {
  const opening = books.journal.some(isOpening) || (books.journal.length > 0 && journalFromStart(books.journal));
  const kinds: [string, Set<string>][] = [[PAYABLE, new Set(cfg.payable_codes.map((c) => squash(c)))], [LOAN, new Set(cfg.loan_codes.map((c) => squash(c)))],
    [DEPOSIT, new Set(cfg.deposit_codes.map((c) => squash(c)))]];
  const ref = books.book_date;
  interface E { kind: string; code: string; account: string; vendor: string; vcode: string; sum: number; unknown: boolean; due: IsoDate | null;
    joins?: IsoDate[]; mats?: IsoDate[]; guess?: number }
  const acc = new Map<string, E>();
  for (const ln of books.journal) {
    const code = squash(ln.account_code);
    const kind = kinds.find(([, cs]) => cs.has(code))?.[0];
    if (kind === undefined || (ref !== null && ln.date !== null && ln.date > ref)) continue;
    const vcode = normCode(ln.vendor_code);
    const key = [kind, code, vcode || "이름:" + normVendor(ln.vendor || "")].join("\u0000");
    if (!acc.has(key)) acc.set(key, { kind, code, account: ln.account || "", vendor: pyStrip(ln.vendor || ""), vcode, sum: 0, unknown: false, due: null });
    const e = acc.get(key)!;
    if (ln.debit === null && ln.credit === null) e.unknown = true;
    else e.sum += (kind === DEPOSIT ? 1 : -1) * ((ln.debit || 0) - (ln.credit || 0));
    if (kind === DEPOSIT || kind === LOAN) {
      const md = memoDate(ln.memo);
      if (md !== null && (e.due === null || md > e.due)) e.due = md;
    }
    if (kind === DEPOSIT && ln.date !== null) {
      if (ln.debit) (e.joins ??= []).push(ln.date);
      if (ln.credit) (e.mats ??= []).push(ln.date);
    }
  }
  const maxD = (xs: IsoDate[]) => xs.reduce((a, b) => (b > a ? b : a));
  const terms = new Map<string, [IsoDate, number]>();
  for (const e of acc.values()) {
    const joins = e.joins ?? [], mats = e.mats ?? [];
    if (e.kind === DEPOSIT && e.sum === 0 && joins.length === 1 && mats.length && maxD(mats) > joins[0]!) {
      const mm = maxD(mats);
      if (!terms.has(e.code) || mm > terms.get(e.code)![0]) terms.set(e.code, [mm, daysBetween(joins[0]!, mm)]);
    }
  }
  for (const e of acc.values()) {
    if (e.kind !== DEPOSIT || e.due !== null || e.sum <= 0) continue;
    const joins = e.joins ?? [];
    if (joins.length === 1 && !(e.mats && e.mats.length) && terms.has(e.code)) {
      e.due = addDays(joins[0]!, terms.get(e.code)![1]);
      e.guess = terms.get(e.code)![1];
    }
  }
  const rows: TRow[] = [];
  const day = ref ?? "";
  for (const e of sortedBy([...acc.values()], (x) => [x.kind !== PAYABLE, x.code, -x.sum])) {
    if (!e.unknown && e.sum === 0) continue;
    rows.push({ "구분": e.kind, "계정코드": e.code, "계정과목": e.account, "거래처코드": e.vcode, "거래처": e.vendor, "잔액": e.unknown ? "" : String(e.sum),
      "기준일": day, "만기일": e.due ?? "", "만기근거": !e.due ? "" : e.guess ? `지난 정기예금 기간 ${e.guess}일로 추정` : "적요", "전기이월": opening ? "있음" : "없음" });
  }
  const tot = (k: string) => rows.filter((r) => r["구분"] === k && r["잔액"]).reduce((a, r) => a + Number(r["잔액"]), 0);
  const cnt = (k: string) => rows.filter((r) => r["구분"] === k).length;
  const note = `장부 채무·정기예금 (${day || "날짜 없음"} 기준${opening ? "" : ", 분개장에 전기이월 없음: 올해 늘고 준 금액만"}): 미지급금 ${cnt(PAYABLE)}곳 ${fmt(tot(PAYABLE))}원 · 차입금 ${cnt(LOAN)}줄 ${fmt(tot(LOAN))}원 · 정기예금 ${cnt(DEPOSIT)}줄 ${fmt(tot(DEPOSIT))}원 (만기일 모름 ${rows.filter((r) => r["구분"] === DEPOSIT && !r["만기일"]).length}줄)`;
  return new Table(DEBT_FILE, DEBT_KEYS, rows, { notes: [note] });
}

/** build_bank */
export function buildBank(books: Books, cfg: Cfg): Table[] {
  const TXN = SCHEMA["입출금내역.csv"]!;
  const cash = new Set(cfg.cash_codes.map((c) => squash(c)));
  let lines = books.journal.filter((ln) => cash.has(squash(ln.account_code)) && ln.date !== null);
  if (!lines.length) {
    const why = `분개장에 보통예금(${cfg.cash_codes.join(",")}) 줄 없음`;
    return [new Table(BOOK_BAL_FILE, BOOK_BAL_KEYS, [], { written: false, reason: why }), new Table(BOOK_TXN_FILE, TXN, [], { written: false, reason: why })];
  }
  if (!books.from_start) {
    const first = lines.map((ln) => ln.date!).reduce((a, b) => (b < a ? b : a));
    const why = books.start_gap ? `${books.start_gap} → 통장 잔액은 계좌잔액.csv 사용`
      : `작년 분개장 없음 (분개장 ${first}부터, 전기이월·설립 자본금 줄 없음) → 통장 잔액은 계좌잔액.csv 사용`;
    return [new Table(BOOK_BAL_FILE, BOOK_BAL_KEYS, [], { notes: [why] }), new Table(BOOK_TXN_FILE, TXN, [], { notes: [why] })];
  }
  lines = sortedBy(lines, (ln) => [ln.date!, String(ln.no || "")]);
  const sk = (d: IsoDate | null, no: string) => (d ?? "") + "\u0000" + no;
  const slips = new Map<string, [boolean, boolean]>();
  for (const ln of lines) {
    const k = sk(ln.date, ln.no);
    if (!slips.has(k)) slips.set(k, [false, false]);
    const v = slips.get(k)!;
    v[0] = v[0] || !!ln.debit;
    v[1] = v[1] || !!ln.credit;
  }
  const acct = (ln: JLine) => pyStrip(ln.vendor || "") || "보통예금 (거래처 없음)";
  const others = new Map<string, JLine[]>();
  for (const o of books.journal) {
    if (o.date !== null && !cash.has(squash(o.account_code))) {
      const k = sk(o.date, o.no);
      if (!others.has(k)) others.set(k, []);
      others.get(k)!.push(o);
    }
  }
  const txns: TRow[] = [], snaps: TRow[] = [];
  const bal = new Map<string, number>();
  const last = lines[lines.length - 1]!.date!;
  const snap = (day: IsoDate) => {
    for (const [a, v] of bal) snaps.push({ "기준일": day, "계좌명": a, "은행": "", "잔액": String(v) });
  };
  let me: IsoDate | null = null;
  for (const ln of lines) {
    const d = ln.date!;
    while (me !== null && d > me) {
      snap(me);
      me = monthEnd(addDays(me, 1));
    }
    if (me === null) me = monthEnd(d);
    const a = acct(ln);
    const v = (ln.debit || 0) - (ln.credit || 0);
    bal.set(a, (bal.get(a) ?? 0) + v);
    if (v) {
      const both = slips.get(sk(d, ln.no))!;
      const cat = both[0] && both[1] ? TRANSFER : "";
      const memo = pyStrip(ln.memo || "");
      const side = v < 0 ? "debit" : "credit";
      const party = (others.get(sk(d, ln.no)) ?? []).filter((o) => o[side] && pyStrip(o.vendor || ""));
      let parts: [string, number][];
      if (!cat && party.length > 1 && party.reduce((s, o) => s + (o[side] as number), 0) === Math.abs(v)) {
        parts = party.map((o) => [pyStrip(o.vendor || ""), o[side] as number]);
      } else {
        const names = [...new Set(party.map((o) => pyStrip(o.vendor || "")))].sort(cmpStr);
        parts = [[names.length === 1 ? names[0]! : "", Math.abs(v)]];
      }
      for (const [vend, amt] of parts) {
        txns.push({ "일자": d, "계좌명": a, "입출금": v > 0 ? "입금" : "출금", "금액": String(amt), "분류": cat, "프로젝트번호": "", "거래처": vend, "적요": memo });
      }
    }
  }
  if (me !== null && me < last) snap(me);
  snap(last);
  const total = [...bal.values()].reduce((s, x) => s + x, 0);
  const note = `보통예금 잔액 = 분개장 ${lines[0]!.date}부터 차변−대변 누적 (기초 잔액 0) · 계좌 ${bal.size}개 · ${last} 합계 ${won(total)}`;
  return [new Table(BOOK_BAL_FILE, BOOK_BAL_KEYS, snaps, { notes: [note] }),
    new Table(BOOK_TXN_FILE, TXN, txns, { notes: [`보통예금 입출금 ${txns.length}줄 (같은 전표에 차변·대변 모두 있으면 계좌간이체)`] })];
}

/** build_tax */
export function buildTax(files: ConvFiles, books: Books, cfg: Cfg, asof: IsoDate, inputDir: string | null, wehagoDir: string | null, today: IsoDate): Table {
  const okMode = ["자동", "반기", "매월"].includes(cfg.withholding_mode);
  const mode = okMode ? cfg.withholding_mode : "자동";
  const [cardDays, cardNotes] = inputDir ? tax.readCardDays(files, inputDir) : [new Map(), [] as string[]];
  const [scrNotes, scr] = wehagoDir ? compareScreens(books.journal, rawFiles(files, wehagoDir), asof, cfg.withholding_codes, cfg.withholding_vendors,
    cfg.insurance_vendors) : [[] as string[], new Map<string, number>()];
  const [cardReal, cardUpto] = wehagoDir ? cardUsage(files, wehagoDir) : [new Map(), null];
  const J = books.journal;
  let rows = [...tax.vat(J, asof, cfg.vat_payable_codes, cfg.vat_codes), ...tax.withholding(J, asof, cfg.withholding_codes, cfg.withholding_vendors, mode, scr),
    ...tax.social(J, asof, cfg.withholding_codes, cfg.insurance_vendors), ...tax.salary(J, asof, cfg.salary_codes, ["26200"], cfg.salary_pay_day),
    ...tax.cards(J, asof, cardDays, ["26200"], cardReal, cardUpto), ...tax.deposits(J, asof)];
  const L: Law = { files, inputDir, today };
  const manual = inputDir ? readManual(files, inputDir) : new Map<string, number>();
  const [ctRows, ctNote] = fromJournal(L, J, cfg, asof, manual, wehagoDir);
  rows.push(...ctRows);
  rows.push(...carryRows(L, J, cfg, asof, manual, wehagoDir));
  rows.push(...tax.fixedCosts(J, asof, rows.flatMap((r) => (r["거래처코드"] || "").split(/\s+/u).filter((c) => c))));
  rows = sortedBy(rows, (r) => r["납부예정일"] || "9999");
  const notes = rows.map((r) => `${r["세목"]} ${r["대상기간"]} → ${r["납부예정일"] || "날짜 미정"} ${r["세목"] === tax.DEPOSIT_IN ? "입금" : "납부"} ${r["금액"] ? fmt(Math.trunc(Number(r["금액"]))) : "미확인"}원 (${r["상태"]})`);
  if (!okMode) notes.push(`설정 변환_원천세납부 값 '${cfg.withholding_mode}' 사용할 수 없음 → 자동`);
  notes.push(...cardNotes, ...scrNotes);
  const thin = rows.filter((r) => r["세목"] === "카드대금" && (r["근거"] ?? "").startsWith(tax.CARD_THIN_MARK));
  if (thin.length) {
    notes.push(`[확인] 카드 전표 입력 전으로 보임: ${thin.map((r) => (r["대상기간"] ?? "").replaceAll(" (전표 입력 전 추정)", "")).join(", ")} — 전표가 덜 들어간 카드는 최근 3달 평균을 예상으로 더 잡음. 카드 비용은 전표를 넣기 전까지 프로젝트 원가·수익률에 빠져 있음`);
  }
  notes.push(ctNote);
  notes.push("확정된 세금·4대보험이 자금계획서·자금일정에 있으면 보고서는 계산값 대신 그 금액을 씀. 이미 통장에서 낸 것은 넣지 않음");
  return new Table(tax.FILE, tax.COLUMNS, rows, { notes });
}

/** fundplan_opening_checks */
function fundplanOpeningChecks(openings: [[number, number], number, string][], books: Books, cfg: Cfg): string[] {
  if (!openings.length) return [];
  if (!books.from_start) {
    return [`자금계획서 전월이월 대조 안 함: ${books.start_gap ? `${books.start_gap}라` : "작년 분개장이 없어"} 보통예금 잔액을 셀 수 없음`];
  }
  const cash = new Set(cfg.cash_codes.map((c) => squash(c)));
  const out: string[] = [];
  for (const [[y, m], amount, name] of openings) {
    const first = ymd(y, m, 1);
    const prevDay = addDays(first, -1);
    if (books.book_date !== null && books.book_date < prevDay) {
      out.push(`${name} 전월이월 대조 안 함: 분개장이 ${books.book_date}까지라 전월말 잔액을 모름`);
      continue;
    }
    const bal = books.journal.filter((ln) => ln.date !== null && ln.date < first && cash.has(squash(ln.account_code)))
      .reduce((s, ln) => s + ((ln.debit || 0) - (ln.credit || 0)), 0);
    if (bal === amount) out.push(`${name} 전월이월 ${fmt(amount)}원 = 분개장 ${prevDay} 보통예금 잔액 (일치)`);
    else out.push(`[확인] ${name} 전월이월 ${fmt(amount)}원 ≠ 분개장 ${prevDay} 보통예금 잔액 ${fmt(bal)}원 (차이 ${fmt(amount - bal)}원) — 자금계획서와 분개장 받은 시점이 다르거나 장부가 바뀜`);
  }
  return out;
}

/** build_fundplan */
export function buildFundplan(files: ConvFiles, books: Books, cfg: Cfg, wehagoDir: string, asof: IsoDate, mtimes: Record<string, number> = {}): Table {
  const res = fundplan.load(files, wehagoDir, mtimes);
  const notes = [...res.notes];
  if (!res.rows.length) {
    const reason = !notes.length ? "자금계획서(현금대비잔액·지출입금현황) 파일 없음 (기존 파일 그대로)" : "쓸 수 있는 자금계획서 없음 (기존 파일 그대로): " + notes.join(" / ");
    return new Table("자금계획.csv", fundplan.COLUMNS, [], { written: false, reason });
  }
  const counts = fundplan.settle(res.rows, books, asof, cfg.payable_codes, cfg.receivable_codes, cfg.cash_codes);
  const stamps = [...new Set(res.months.map((m) => m[2]))].sort(cmpStr);
  const gap = daysBetween(books.book_date!, stamps[stamps.length - 1]!);
  notes.push(`자료일 ${stamps.join(", ")} · 장부 기준일 ${books.book_date}${gap > 0 ? ` — 그 사이 ${gap}일의 지급·입금은 분개장으로 확인 못함` : ""}`);
  notes.push("분개장 대조: " + fundplan.STATES.map((k) => `${k} ${counts[k]}`).join(" · "));
  notes.push(...fundplanOpeningChecks(res.openings ?? [], books, cfg));
  for (const r of res.rows) {
    if (r["상태"] !== "예정") notes.push(`  ${r["상태"]} ${r["예정일"]} ${r["입출금"]} ${r["거래처"]} ${fmt(r["금액"] as number)}원 — ${r["근거"]}`);
  }
  return new Table("자금계획.csv", fundplan.COLUMNS, res.rows as TRow[], { notes,
    extra: { received: res.months.map(([ym, n, stamp]) => ({ "대상월": ym, "자료일": stamp, "파일": n })), companies: res.companies ?? {} } });
}

export function fundplanReceivedTable(fp: Table): Table {
  if (!fp.written) return new Table(FUNDPLAN_RECEIVED_FILE, FUNDPLAN_RECEIVED_KEYS, [], { written: false, reason: "자금계획.csv 를 만들지 않아 그대로 둠" });
  return new Table(FUNDPLAN_RECEIVED_FILE, FUNDPLAN_RECEIVED_KEYS, (fp.extra["received"] as TRow[]) ?? []);
}

export function bookNoteTable(books: Books): Table {
  return new Table(BOOK_NOTE_FILE, BOOK_NOTE_KEYS, books.notes.filter((n) => String(n).startsWith("[확인]")).map((n) => ({ "알림": n })));
}
