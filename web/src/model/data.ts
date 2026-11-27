// ceo_report/data.py load(folder) 를 파일 묶음(FileSet)으로. 같은 알림 글·같은 속성 이름(파이썬 d.<이름>)을 쓴다.
// 이것이 부르는 읽기도 함께 옮김: paydetail/payreq.read_checked, targets.read, corptax.read(+read_ledger),
// budget.read_confirmed, debts.load(+reconcile.read_maturity).
import { dictReader, readCsv, type CsvInfo, type FileSet } from "./csv";
import { ymd, type IsoDate } from "./dates";
import { PY_SPACE, cmpStr, fmtComma, pyFloatParse, pyIntParse, pyIsDigit, pySplit, pyStrip } from "./py";
import { Issues, num, parseDate, pyStr, rget, type Row } from "./util";
import { normCode } from "./vendor";

export type { FileSet } from "./csv";

export const SCHEMA: Record<string, string[]> = {
  "설정.csv": ["항목", "값"],
  "계좌잔액.csv": ["기준일", "계좌명", "은행", "잔액", "사용제한금액", "제한사유"],
  "입출금내역.csv": ["일자", "계좌명", "입출금", "금액", "분류", "프로젝트번호", "거래처", "적요"],
  "자금일정.csv": ["예정일", "입출금", "금액", "확정여부", "분류", "프로젝트번호", "거래처", "근거", "비고"],
  "프로젝트.csv": ["프로젝트번호", "프로젝트명", "팀", "클라이언트", "상태", "사전견적예산", "예산수정일",
    "계약금액", "매출반영누계", "행사일", "완료일"],
  "프로젝트집행.csv": ["프로젝트번호", "항목", "거래처", "상태", "공급가액", "부가세", "일자", "확정여부", "근거"],
  "계산서.csv": ["프로젝트번호", "거래처", "발행일", "구분", "공급가액", "부가세", "입금예정일", "예정일확정",
    "입금일", "입금액"],
  "손익.csv": ["출처", "연월", "단위", "대상", "매출", "직접비", "공통비", "잠정"],
  "지급계획.csv": ["주시작일", "프로젝트번호", "거래처", "계획금액"],
  "변경내역.csv": ["변경일", "항목", "대상", "변경전", "변경후", "사유"],
  "자료기준일.csv": ["자료", "기준일", "비고"],
  "자료차이.csv": ["항목", "자료A", "금액A", "자료B", "금액B", "상태"],
};

export const FUNDPLAN_FILE = "자금계획.csv";
export const FUNDPLAN_KEYS = ["예정일", "입출금", "거래처", "금액", "대상월", "자료일", "상태"];
export const FUNDPLAN_RECEIVED_FILE = "자금계획받은달.csv";
export const DEPT_FILE = "부서비용.csv";
export const DEPT_KEYS = ["연월", "부서", "급여", "판관비", "인원"];
export const ACCOUNT_FILE = "계정별비용.csv";
export const ACCOUNT_KEYS = ["연월", "구분", "계정코드", "계정과목", "금액"];
export const EVID_FILE = "증빙월별.csv";
export const EVID_KEYS = ["연월", "매출", "매입"];
export const NO_DEPT = "부서 없음";
export const STAFF_FILE = "사원급여.csv";
export const STAFF_KEYS = ["연월", "부서", "사원명", "급여"];
export const DEPT_ACCOUNT_FILE = "부서계정비용.csv";
export const DEPT_ACCOUNT_KEYS = ["연월", "부서", "계정코드", "계정과목", "금액"];
export const BOOK_BAL_FILE = "장부잔액.csv";
export const BOOK_BAL_KEYS = ["기준일", "계좌명", "은행", "잔액"];
export const BOOK_TXN_FILE = "장부입출금.csv";
export const BOOK_NOTE_FILE = "장부알림.csv";
export const BOOK_NOTE_KEYS = ["알림"];
export const TAX_FILE = "세금예상.csv";
export const TAX_KEYS = ["세목", "대상기간", "납부예정일", "금액", "상태"];
export const OUTFLOW_KEYS: Record<string, string[]> = {
  "자금일정.csv": ["예정일", "입출금", "금액"],
  "프로젝트집행.csv": ["상태", "공급가액", "일자"],
};
export const INFLOW_KEYS: Record<string, string[]> = {
  "계산서.csv": ["프로젝트번호", "공급가액", "부가세", "입금예정일", "입금액"],
};
export const PRIOR_TAG = "참고(지난해 프로젝트)";
export const EXEC_STATES = ["지급완료", "요청미지급", "카드사용미결제", "카드결제완료", "집행계획미요청"];
export const INVOICE_KINDS = ["발행", "선수금", "수정", "취소", "환불"];
export const TRANSFER = "계좌간이체";
/** calc.INTRANET_IN_FUNDS (data.load 가 calc 에서 읽는 값) */
export const INTRANET_IN_FUNDS = false;

export const DEFAULT_SETTINGS: Record<string, string> = {
  "회사명": "회사명",
  "첫화면_프로젝트_표시수": "10",
  "위험_최소보유현금": "100000000",
  "위험_미수경과일": "30",
  "위험_미발행경과일": "30",
  "위험_자료경과일": "7",
  "위험_예산초과율": "100",
  "예산_원가율": "0.70",
};

export function isPrior(e: { basis?: unknown }): boolean {
  const b = e.basis;
  return (b ? pyStr(b) : "").includes(PRIOR_TAG);
}

// ───────────── 자료 모양 (파이썬 dict 키 그대로) ─────────────
export interface Balance {
  date: IsoDate; account: string; bank: string; balance: number | null; restricted: number | null; reason: string;
  row: Row; release: IsoDate | null;
  /** 장부 정기예금 줄에만 있음 */
  release_guess?: boolean;
}
export interface Txn {
  date: IsoDate; account: string; io: string; amount: number; cat: string; project: string; vendor: string; memo: string; row: Row;
}
export interface Sched {
  date: IsoDate | null; io: string; amount: number | null; firm: boolean; cat: string; project: string; vendor: string;
  vendor_code: string; basis: string; memo: string; source: string; row: Row;
}
export interface FundplanRow {
  date: IsoDate; io: string; cat: string; vendor: string; vendor_code: string; amount: number; ym: string; stamp: IsoDate;
  state: string; basis: string; file: string; row: Row; project: string; origin: string;
}
export interface DeptRow {
  ym: string; dept: string; salary: number | null; sga: number | null; heads: number | null;
  nonop_in: number | null; nonop_out: number | null; has_nonop: boolean;
}
export interface StaffRow { ym: string; dept: string; name: string; salary: number | null }
export interface DeptAccountRow { ym: string; dept: string; code: string; account: string; amount: number | null }
export interface AccountRow { ym: string; group: string; code: string; name: string; amount: number | null }
export interface PayDetail { vendor: string; amount: number; text: string; source: string }
export interface PayRequest { key: string; project: string; vendor: string; amount: number | null; note: string }
export interface TeamTarget { revenue: number | null; rate: number | null }
export interface BudgetConfirmedYear {
  date: string;
  /** 키 "월|대상" (파이썬 튜플 (int(월), 대상)) → {매출, 매출총이익, 급여, 판관비, 감가상각비, 영업외수익, 영업외비용} */
  rows: Record<string, Record<string, number | null>>;
}
export interface TaxRow {
  kind: string; period: string; due: IsoDate | null; amount: number | null; state: string; basis: string;
  codes: string[]; book: IsoDate | null; base: number | null; calc: number | null; prepaid: number | null;
}
export interface DebtRow {
  kind: string; code: string; account: string; vcode: string; vendor: string; balance: number | null;
  date: string; due: string; due_basis: string; opening: boolean;
  /** 대출만기.csv 에 그 거래처코드 줄이 있는 차입금만 */
  yearly?: boolean; extend_note?: string;
}
export interface Project {
  id: string; name: string; team: string; client: string; state: string; estimate: number | null; estimate_raw: string;
  budget_date: IsoDate | null; contract: number | null; recognized: number | null; event_date: string;
  quote: number | null; exec_budget: number | null; approval: string; done_date: IsoDate | null; row: Row;
}
export interface Exec {
  project: string; item: string; vendor: string; state: string; supply: number | null; vat: number | null;
  date: IsoDate | null; firm: boolean; basis: string; row: Row;
}
export interface Invoice {
  project: string; client: string; date: IsoDate | null; kind: string; supply: number | null; vat: number | null;
  due: IsoDate | null; due_firm: boolean; paid_date: IsoDate | null; paid: number | null; row: Row;
}
export interface PlRow {
  source: string; ym: string; unit: string; target: string; revenue: number | null; direct: number | null;
  common: number | null; provisional: boolean; row: Row;
}
export interface PlanRow { week: IsoDate | null; project: string; vendor: string; amount: number | null; row: Row }
export interface ChangeRow { date: IsoDate | null; field: string; target: string; before: string; after: string; reason: string }
export interface AsofRow { name: string; date: IsoDate | null; memo: string }
export interface DiffRow { item: string; a: string; a_amt: number | null; b: string; b_amt: number | null; state: string }

export interface Data {
  issues: Issues;
  present: Record<string, boolean>;
  out_missing: string[];
  in_missing: string[];
  settings: Record<string, string>;
  settings_line: Record<string, number | string>;
  book_bank: boolean;
  balances: Balance[];
  txns: Txn[];
  schedule: Sched[];
  fundplan: FundplanRow[] | null;
  fundplan_problem: string;
  fundplan_received: string[];
  fundplan_received_at: Record<string, IsoDate>;
  dept: DeptRow[] | null;
  dept_problem: string;
  staff: StaffRow[] | null;
  dept_accounts: DeptAccountRow[] | null;
  /** 연월 → [매출, 매입] */
  evid_month: Record<string, [number | null, number | null]> | null;
  accounts: AccountRow[] | null;
  accounts_problem: string;
  pay_details: PayDetail[];
  pay_requests: PayRequest[];
  /** 키 "연도|팀" (파이썬 튜플 키) */
  team_targets: Record<string, TeamTarget>;
  /** 키 "연도" = 직접 입력, "대장|연도" = 위하고 고정자산대장 (파이썬 ("대장", 연도)) */
  dep_manual: Record<string, number>;
  budget_confirmed: Record<string, BudgetConfirmedYear>;
  tax: TaxRow[] | null;
  debts: DebtRow[] | null;
  projects: Record<string, Project>;
  project_order: string[];
  execs: Exec[];
  invoices: Invoice[];
  pl: PlRow[];
  plans: PlanRow[];
  changes: ChangeRow[];
  asof: AsofRow[];
  diffs: DiffRow[];
}

// ───────────── 도움 함수 ─────────────
const has = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k);

/** r.get(k, dflt) */
function g(r: Row, k: string, dflt = ""): string {
  const v = rget(r, k);
  return v === undefined ? dflt : v;
}
/** (r.get(k) or "") */
function go(r: Row, k: string): string {
  return rget(r, k) || "";
}
/** (r.get(k) or "").strip() */
function gs(r: Row, k: string): string {
  return pyStrip(go(r, k));
}

function check(iss: Issues, row: Row, col: string, value: string, allowed: string[]): boolean {
  if (!allowed.includes(value)) {
    iss.add(row._file, row._line, `${col} 값 '${value}'은(는) 허용 값이 아님 (${allowed.join("/")})`);
    return false;
  }
  return true;
}

function outflow(iss: Issues, row: Row, col: string, value: number | null): number | null {
  if (value !== null && value < 0) {
    iss.add(row._file, row._line, `${col} 값이 음수: '${g(row, col)}' → 지급 금액 ${fmtComma(-value)}원으로 처리 (지급을 줄이지 않음)`);
    return -value;
  }
  return value;
}

function unusable(files: FileSet, fname: string, ok: boolean, lost: string[]): string | null {
  if (!has(files, fname)) return `${fname} (파일 없음)`;
  if (!ok) return `${fname} (읽지 못함)`;
  if (lost.length) return `${fname} (필수 열 없음: ${lost.join(", ")})`;
  return null;
}

/** int(t) for t that passed str.isdigit() (파이썬은 위첨자 숫자 등에서 멈추지만 여기서는 null). */
function intDigits(t: string): number | null {
  return pyIntParse(t);
}

/** targets._int / corptax._int: 쉼표·'원' 빼고 isdigit 이면 정수. */
function plainInt(text: string | null | undefined): number | null {
  const t = pyStrip((text || "").replace(/,/g, "").replace(/원/g, ""));
  return pyIsDigit(t) ? intDigits(t) : null;
}

/** targets._rate */
function rate(text: string | null | undefined): number | null {
  const t = pyStrip((text || "").replace(/%/g, ""));
  const v = pyFloatParse(t);
  if (v === null) return null;
  return v >= 0 && v <= 100 ? v : null;
}

/** dt.date(*[int(v) for v in s.split("-")]) — 못 하면 null. */
function dateParts(s: string): IsoDate | null {
  const parts = s.split("-");
  if (parts.length !== 3) return null;
  const ns = parts.map((p) => pyIntParse(p));
  if (ns.some((n) => n === null)) return null;
  try {
    return ymd(ns[0] as number, ns[1] as number, ns[2] as number);
  } catch {
    return null;
  }
}

/** debts._valid_day: dt.date.fromisoformat(text.strip()) 가 되는가 (YYYY-MM-DD·YYYYMMDD). */
function validDay(text: string | undefined): boolean {
  const t = pyStrip(text || "");
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t) ?? /^(\d{4})(\d{2})(\d{2})$/.exec(t);
  if (!m) return false;
  try {
    ymd(Number(m[1]), Number(m[2]), Number(m[3]));
    return true;
  } catch {
    return false;
  }
}

// ───────────── 딸린 파일 읽기 ─────────────
const PAY_DETAIL_FILE = "출금상세.csv";
const PAY_REQUEST_FILE = "지급요청서.csv";

/** paydetail.read_checked */
export function readPayDetails(files: FileSet): [PayDetail[] | null, string | null] {
  if (!has(files, PAY_DETAIL_FILE)) return [[], null];
  const iss = new Issues();
  const info: CsvInfo = {};
  const [rows, ok] = readCsv(PAY_DETAIL_FILE, files[PAY_DETAIL_FILE], ["거래처", "금액", "상세내역"], iss, info);
  if (!ok || (info.missing && info.missing.length)) return [null, iss.items.map((x) => x[2]).join("; ") || "읽지 못함"];
  const out: PayDetail[] = [];
  for (const r of rows) {
    const v = gs(r, "거래처");
    const t0 = pyStrip(go(r, "금액").replace(/,/g, "").replace(/원/g, ""));
    const a = pyIsDigit(t0.replace(/^-+/, "")) ? intDigits(t0) : null;
    const t = gs(r, "상세내역");
    if (v && a !== null && t) out.push({ vendor: v, amount: a, text: t, source: pyStrip(rget(r, "출처") || "수기") || "수기" });
  }
  return [out, null];
}

const PID_RE = /(?<![0-9])([0-9]{5})(?![0-9])/;
const AMT_STRIP = new RegExp("[," + PY_SPACE + "원]", "g");

/** payreq.read_checked */
export function readPayRequests(files: FileSet): [PayRequest[] | null, string | null] {
  if (!has(files, PAY_REQUEST_FILE)) return [[], null];
  const iss = new Issues();
  const info: CsvInfo = {};
  const [rows, ok] = readCsv(PAY_REQUEST_FILE, files[PAY_REQUEST_FILE], ["키", "프로젝트", "업체명", "금액", "세부사항"], iss, info);
  if (!ok || (info.missing && info.missing.length)) return [null, iss.items.map((x) => x[2]).join("; ") || "읽지 못함"];
  return [rows.map((r) => {
    const m = PID_RE.exec(go(r, "프로젝트"));
    const t = go(r, "금액").replace(AMT_STRIP, "");
    return {
      key: gs(r, "키"), project: m ? (m[1] as string) : "", vendor: gs(r, "업체명"),
      amount: /^-?[0-9]+(?=\n?$)/.test(t) ? Number(t) : null, note: gs(r, "세부사항"),
    };
  }), null];
}

/** targets.read → {"연도|팀": {...}} */
export function readTargets(files: FileSet): Record<string, TeamTarget> {
  const out: Record<string, TeamTarget> = {};
  const text = files["팀목표.csv"];
  if (text === undefined) return out;
  for (const r of dictReader(text)) {
    const y = pyStrip(r["연도"] || ""), team = pyStrip(r["팀"] || "");
    if (pyIsDigit(y) && team) out[`${y}|${team}`] = { revenue: plainInt(r["매출목표"]), rate: rate(r["목표수익률"]) };
  }
  return out;
}

/** corptax.read (+ read_ledger 의 입력 폴더 고정자산.csv) */
export function readDep(files: FileSet): Record<string, number> {
  const out: Record<string, number> = {};
  const text = files["감가상각비.csv"];
  if (text !== undefined) {
    for (const r of dictReader(text)) {
      const y = pyStrip(r["연도"] || ""), v = plainInt(r["연간감가상각비"]);
      if (pyIsDigit(y) && v !== null) out[y] = v;
    }
  }
  const ledger: Record<string, number> = {};
  const lt = files["고정자산.csv"];
  if (lt !== undefined) {
    for (const r of dictReader(lt)) {
      const y = pyStrip(r["기준연도"] || ""), v = plainInt(r["당기상각"]);
      if (pyIsDigit(y) && v !== null) ledger[y] = (ledger[y] ?? 0) + v;
    }
  }
  for (const [y, v] of Object.entries(ledger)) out[`대장|${y}`] = v;
  return out;
}

const CONFIRM_VALUE_KEYS = ["매출", "매출총이익", "급여", "판관비", "감가상각비", "영업외수익", "영업외비용"];
const CONFIRM_NUM = /^-?\p{Nd}+(\.\p{Nd}+)?(?=\n?$)/u;

/** budget.read_confirmed */
export function readConfirmed(files: FileSet): Record<string, BudgetConfirmedYear> {
  const out: Record<string, BudgetConfirmedYear> = {};
  const text = files["예산확정.csv"];
  if (text === undefined) return out;
  for (const r of dictReader(text)) {
    const y = pyStrip(r["연도"] || ""), m = pyStrip(r["월"] || ""), who = pyStrip(r["대상"] || "");
    if (!(pyIsDigit(y) && pyIsDigit(m) && who)) continue;
    if (!has(out, y)) out[y] = { date: pyStrip(r["확정일"] || ""), rows: {} };
    const Y = out[y] as BudgetConfirmedYear;
    const v: Record<string, number | null> = {};
    for (const k of CONFIRM_VALUE_KEYS) {
      const t = pyStrip((r[k] || "").replace(/,/g, ""));
      v[k] = CONFIRM_NUM.test(t) ? Math.trunc(pyFloatParse(t) as number) : null;
    }
    Y.rows[`${intDigits(m)}|${who}`] = v;
  }
  return out;
}

const MATURITY_KEYS = ["거래처코드", "차입처", "새만기일", "매년연장", "메모"];
const MATURITY_DEFAULT: Record<string, string>[] = [
  { "거래처코드": "256", "차입처": "신한 기술보증기금 2억", "새만기일": "2027-04-17", "매년연장": "예", "메모": "2026-11-14 사용자: 연장함, 매년 연장" },
  { "거래처코드": "1107", "차입처": "신한 기술보증기금 3억", "새만기일": "", "매년연장": "예", "메모": "2026-11-14 사용자: 매년 연장 (만기일은 위하고 값 그대로)" },
];

/** reconcile.read_maturity */
export function readMaturity(files: FileSet): Record<string, Record<string, string>> {
  const text = files["대출만기.csv"];
  const rows: Record<string, string | null | undefined>[] = text === undefined ? MATURITY_DEFAULT.map((r) => ({ ...r })) : dictReader(text);
  const out: Record<string, Record<string, string>> = {};
  for (const r of rows) {
    const k = normCode(r["거래처코드"] ?? null);
    if (k) {
      const o: Record<string, string> = {};
      for (const kk of MATURITY_KEYS) o[kk] = pyStrip(r[kk] || "");
      out[k] = o;
    }
  }
  return out;
}

const DEBT_FILE = "장부채무.csv";
const DEBT_REQUIRED = ["구분", "계정코드", "계정과목", "거래처코드", "거래처", "잔액", "기준일"];
const LOAN = "차입금";

/** debts.load */
export function loadDebts(files: FileSet, iss: Issues): DebtRow[] | null {
  if (!has(files, DEBT_FILE)) return null;
  const info: CsvInfo = {};
  const [rows, ok] = readCsv(DEBT_FILE, files[DEBT_FILE], DEBT_REQUIRED, iss, info);
  if (!ok || (info.missing && info.missing.length)) return null;
  const out: DebtRow[] = rows.map((r) => ({
    kind: gs(r, "구분"), code: gs(r, "계정코드"), account: go(r, "계정과목"), vcode: gs(r, "거래처코드"),
    vendor: gs(r, "거래처"), balance: pyStrip(go(r, "잔액")) ? num(rget(r, "잔액")) : null,
    date: gs(r, "기준일"), due: gs(r, "만기일"), due_basis: gs(r, "만기근거"), opening: gs(r, "전기이월") !== "없음",
  }));
  const over = readMaturity(files);
  for (const x of out) {
    const o = x.kind === LOAN && x.vcode ? over[normCode(x.vcode)] : undefined;
    if (!o) continue;
    x.yearly = ["예", "Y", "y", "O", "o", "1"].includes(pyStrip(o["매년연장"] || ""));
    if (validDay(o["새만기일"])) {
      x.due = pyStrip(o["새만기일"] as string);
      x.due_basis = "직접 입력";
    }
    x.extend_note = pyStrip(o["메모"] || "");
  }
  return out;
}

// ───────────── load ─────────────
export function loadData(files: FileSet): Data {
  const iss = new Issues();
  const present: Record<string, boolean> = {};
  const out_missing: string[] = [];
  const in_missing: string[] = [];
  const raw: Record<string, Row[]> = {};
  for (const [fname, cols] of Object.entries(SCHEMA)) {
    const info: CsvInfo = {};
    const [rows, ok] = readCsv(fname, files[fname], cols, iss, info);
    raw[fname] = rows;
    present[fname] = ok;
    for (const [keys, missing] of [[OUTFLOW_KEYS, out_missing], [INFLOW_KEYS, in_missing]] as const) {
      const ks = keys[fname];
      if (ks) {
        const why = unusable(files, fname, ok, ks.filter((c) => (info.missing ?? []).includes(c)));
        if (why) missing.push(why);
      }
    }
  }
  const R = (f: string) => raw[f] as Row[];

  // 설정
  const settings: Record<string, string> = { ...DEFAULT_SETTINGS };
  const settings_line: Record<string, number | string> = {};
  for (const r of R("설정.csv")) {
    const k = rget(r, "항목");
    if (k) {
      settings[k] = g(r, "값");
      settings_line[k] = r._line;
    }
  }

  // 장부잔액·장부입출금
  let book_bank = false;
  if (has(files, BOOK_BAL_FILE) && has(files, BOOK_TXN_FILE)) {
    const [brows, bok] = readCsv(BOOK_BAL_FILE, files[BOOK_BAL_FILE], BOOK_BAL_KEYS, iss, {});
    const [trows, tok] = readCsv(BOOK_TXN_FILE, files[BOOK_TXN_FILE], SCHEMA["입출금내역.csv"] as string[], iss, {});
    if (bok && tok && brows.length) {
      book_bank = true;
      for (const r of R("계좌잔액.csv")) {
        if (pyStrip(go(r, "잔액"))) iss.add(r._file, r._line, "잔액은 분개장 보통예금(장부잔액.csv)으로 계산 → 이 줄은 사용제한만 씀");
        r["잔액"] = "0";
        r["계좌명"] = "사용제한: " + (rget(r, "계좌명") || rget(r, "제한사유") || "");
      }
      if (R("입출금내역.csv").length) iss.add("입출금내역.csv", "-", "입출금은 분개장 보통예금(장부입출금.csv)으로 계산 → 이 파일은 쓰지 않음");
      raw["계좌잔액.csv"] = [...brows, ...R("계좌잔액.csv")];
      raw["입출금내역.csv"] = trows;
      present["계좌잔액.csv"] = present["입출금내역.csv"] = true;
    }
  }

  if (has(files, BOOK_NOTE_FILE)) {
    for (const r of readCsv(BOOK_NOTE_FILE, files[BOOK_NOTE_FILE], BOOK_NOTE_KEYS, iss, {})[0]) {
      const text = gs(r, "알림");
      if (text) iss.add(BOOK_NOTE_FILE, "-", text.replace("[확인] ", ""));
    }
  }

  // 계좌잔액
  const balances: Balance[] = [];
  for (const r of R("계좌잔액.csv")) {
    const date = parseDate(rget(r, "기준일"), iss, r, "기준일");
    const account = g(r, "계좌명"), bank = g(r, "은행");
    const balance = num(rget(r, "잔액"), iss, r, "잔액");
    const restricted = num(rget(r, "사용제한금액"), iss, r, "사용제한금액");
    const reason = g(r, "제한사유");
    const release = pyStrip(go(r, "제한해제일")) ? parseDate(rget(r, "제한해제일"), iss, r, "제한해제일") : null;
    if (date === null) {
      iss.add(r._file, r._line, "기준일 없음 → 제외");
      continue;
    }
    balances.push({ date, account, bank, balance, restricted, reason, row: r, release });
  }

  // 입출금내역
  const txns: Txn[] = [];
  for (const r of R("입출금내역.csv")) {
    const date = parseDate(rget(r, "일자"), iss, r, "일자");
    const account = g(r, "계좌명"), io = g(r, "입출금");
    let amount = num(rget(r, "금액"), iss, r, "금액");
    const t = { date, account, io, amount, cat: g(r, "분류") || "미분류", project: g(r, "프로젝트번호"), vendor: g(r, "거래처"), memo: g(r, "적요"), row: r };
    if (!check(iss, r, "입출금", io, ["입금", "출금"]) || date === null || amount === null) {
      iss.add(r._file, r._line, "일자·입출금·금액 중 확인 불가 → 합계에서 제외");
      continue;
    }
    if (io === "출금") amount = outflow(iss, r, "금액", amount) as number;
    txns.push({ ...t, date, amount });
  }

  // 자금일정
  const schedule: Sched[] = [];
  for (const r of R("자금일정.csv")) {
    const io0 = g(r, "입출금");
    const date = parseDate(rget(r, "예정일"), iss, r, "예정일");
    const io = io0 === "출금" ? "지급" : io0;
    const amount = num(rget(r, "금액"), iss, r, "금액");
    const s: Sched = {
      date, io, amount, firm: g(r, "확정여부") === "확정", cat: g(r, "분류") || "미분류", project: g(r, "프로젝트번호"),
      vendor: g(r, "거래처"), vendor_code: gs(r, "거래처코드"), basis: g(r, "근거"), memo: g(r, "비고"), source: "자금일정", row: r,
    };
    if (!check(iss, r, "입출금", s.io, ["입금", "지급"])) continue;
    if (s.io === "지급") s.amount = outflow(iss, r, "금액", s.amount);
    check(iss, r, "확정여부", g(r, "확정여부"), ["확정", "추정", "예상"]);
    if (s.amount === null) iss.add(r._file, r._line, "금액 미확인 → 일정 합계에서 제외, 건수만 표시");
    schedule.push(s);
  }

  // 자금계획 (선택)
  let fundplan: FundplanRow[] | null = null;
  let fundplan_problem = "";
  if (has(files, FUNDPLAN_FILE)) {
    const info: CsvInfo = {};
    const [rows, ok] = readCsv(FUNDPLAN_FILE, files[FUNDPLAN_FILE], FUNDPLAN_KEYS, iss, info);
    const miss = info.missing ?? [];
    if (!ok || miss.length) {
      fundplan_problem = !ok ? "읽지 못함" : "필수 열 없음: " + miss.join(", ");
    } else {
      const fp: FundplanRow[] = [];
      let bad = 0;
      for (const r of rows) {
        const date = parseDate(rget(r, "예정일"), iss, r, "예정일");
        const io = g(r, "입출금"), cat = g(r, "분류"), vendor = g(r, "거래처"), vendor_code = gs(r, "거래처코드");
        const amount = num(rget(r, "금액"), iss, r, "금액");
        const ym = g(r, "대상월");
        const stamp = parseDate(rget(r, "자료일"), iss, r, "자료일");
        const f = {
          date, io, cat, vendor, vendor_code, amount, ym, stamp, state: g(r, "상태") || "예정", basis: g(r, "근거"),
          file: g(r, "파일"), row: r, project: gs(r, "프로젝트"), origin: gs(r, "원전표"),
        };
        if (date === null || amount === null || stamp === null || (io !== "지급" && io !== "입금")) {
          iss.add(r._file, r._line, "예정일·입출금·금액·자료일 중 확인 불가 → 자금계획 전체를 쓰지 않음");
          bad += 1;
        }
        fp.push(f as FundplanRow);
      }
      fundplan = fp;
      if (bad) {
        fundplan = null;
        fundplan_problem = `확인 못한 줄 ${bad}개`;
      }
    }
  }

  const fundplan_received_at: Record<string, IsoDate> = {};
  let fundplan_received: string[] = [];
  if (fundplan !== null && has(files, FUNDPLAN_RECEIVED_FILE)) {
    const got = new Set<string>();
    for (const r of readCsv(FUNDPLAN_RECEIVED_FILE, files[FUNDPLAN_RECEIVED_FILE], ["대상월"], iss, {})[0]) {
      const ym = gs(r, "대상월");
      if (!/^\p{Nd}{4}-\p{Nd}{2}(?=\n?$)/u.test(ym)) continue;
      got.add(ym);
      const stamp = parseDate(rget(r, "자료일"));
      const prev = fundplan_received_at[ym];
      if (stamp !== null && (prev === undefined || stamp > prev)) fundplan_received_at[ym] = stamp;
    }
    fundplan_received = [...got].sort(cmpStr);
  }

  // 부서비용 (선택)
  let dept: DeptRow[] | null = null;
  let dept_problem = "";
  if (has(files, DEPT_FILE)) {
    const info: CsvInfo = {};
    const [rows, ok] = readCsv(DEPT_FILE, files[DEPT_FILE], DEPT_KEYS, iss, info);
    const miss = info.missing ?? [];
    if (!ok || miss.length) {
      dept_problem = !ok ? "읽지 못함" : "필수 열 없음: " + miss.join(", ");
    } else {
      dept = rows.map((r) => {
        const ym = gs(r, "연월"), dp = gs(r, "부서");
        const salary = num(rget(r, "급여"), iss, r, "급여");
        const sga = num(rget(r, "판관비"), iss, r, "판관비");
        const heads = num(rget(r, "인원"), iss, r, "인원");
        const nonop_in = has(r, "영업외수익") ? num(rget(r, "영업외수익"), iss, r, "영업외수익") : null;
        const nonop_out = has(r, "영업외비용") ? num(rget(r, "영업외비용"), iss, r, "영업외비용") : null;
        return { ym, dept: dp, salary, sga, heads, nonop_in, nonop_out, has_nonop: has(r, "영업외수익") && has(r, "영업외비용") };
      });
    }
  }

  // 사원별 급여 (선택)
  let staff: StaffRow[] | null = null;
  if (has(files, STAFF_FILE)) {
    const info: CsvInfo = {};
    const [rows, ok] = readCsv(STAFF_FILE, files[STAFF_FILE], STAFF_KEYS, iss, info);
    if (ok && !(info.missing ?? []).length) {
      staff = rows.map((r) => ({ ym: gs(r, "연월"), dept: gs(r, "부서"), name: gs(r, "사원명"), salary: num(rget(r, "급여"), iss, r, "급여") }));
    }
  }

  // 부서별 판관비 계정과목별 (선택)
  let dept_accounts: DeptAccountRow[] | null = null;
  if (has(files, DEPT_ACCOUNT_FILE)) {
    const info: CsvInfo = {};
    const [rows, ok] = readCsv(DEPT_ACCOUNT_FILE, files[DEPT_ACCOUNT_FILE], DEPT_ACCOUNT_KEYS, iss, info);
    if (ok && !(info.missing ?? []).length) {
      dept_accounts = rows.map((r) => ({
        ym: gs(r, "연월"), dept: gs(r, "부서"), code: gs(r, "계정코드"), account: gs(r, "계정과목"), amount: num(rget(r, "금액"), iss, r, "금액"),
      }));
    }
  }

  // 증빙월별 (선택)
  let evid_month: Record<string, [number | null, number | null]> | null = null;
  if (has(files, EVID_FILE)) {
    const info: CsvInfo = {};
    const [rows, ok] = readCsv(EVID_FILE, files[EVID_FILE], EVID_KEYS, iss, info);
    if (ok && !(info.missing ?? []).length) {
      const em: Record<string, [number | null, number | null]> = {};
      for (const r of rows) {
        const ym = gs(r, "연월");
        if (!ym) continue;
        em[ym] = [num(rget(r, "매출"), iss, r, "매출"), num(rget(r, "매입"), iss, r, "매입")];
      }
      evid_month = em;
    }
  }

  // 계정과목별 (선택)
  let accounts: AccountRow[] | null = null;
  let accounts_problem = "";
  if (has(files, ACCOUNT_FILE)) {
    const info: CsvInfo = {};
    const [rows, ok] = readCsv(ACCOUNT_FILE, files[ACCOUNT_FILE], ACCOUNT_KEYS, iss, info);
    const miss = info.missing ?? [];
    if (!ok || miss.length) {
      accounts_problem = !ok ? "읽지 못함" : "필수 열 없음: " + miss.join(", ");
    } else {
      accounts = rows.map((r) => ({
        ym: gs(r, "연월"), group: gs(r, "구분"), code: gs(r, "계정코드"), name: gs(r, "계정과목"), amount: num(rget(r, "금액"), iss, r, "금액"),
      }));
    }
  }

  // 출금 상세·지급요청서
  const [pd, pdWhy] = readPayDetails(files);
  if (pd === null) iss.add(PAY_DETAIL_FILE, "-", `읽지 못해 상세 내역을 붙이지 않음 (${pdWhy})`);
  const [pr, prWhy] = readPayRequests(files);
  if (pr === null) iss.add(PAY_REQUEST_FILE, "-", `읽지 못해 상세 내역을 붙이지 않음 (${prWhy})`);
  const team_targets = readTargets(files);
  const dep_manual = readDep(files);
  const budget_confirmed = readConfirmed(files);

  // 세금 예상 (선택)
  let tax: TaxRow[] | null = null;
  if (has(files, TAX_FILE)) {
    const info: CsvInfo = {};
    const [rows, ok] = readCsv(TAX_FILE, files[TAX_FILE], TAX_KEYS, iss, info);
    if (ok && !(info.missing ?? []).length) {
      tax = [];
      for (const r of rows) {
        const blank = !pyStrip(go(r, "납부예정일"));
        const due = blank ? null : parseDate(rget(r, "납부예정일"), iss, r, "납부예정일");
        if (due === null && !blank) continue;
        const kind = g(r, "세목"), period = g(r, "대상기간");
        const amount = num(rget(r, "금액"), iss, r, "금액");
        const state = g(r, "상태") || "예상", basis = g(r, "근거");
        const codes = pySplit(go(r, "거래처코드")).filter((c) => c);
        const book = parseDate(rget(r, "장부기준일"), iss, r, "장부기준일");
        const base = pyStrip(go(r, "과세표준")) ? num(rget(r, "과세표준"), iss, r, "과세표준") : null;
        const calc = pyStrip(go(r, "산출세액")) ? num(rget(r, "산출세액"), iss, r, "산출세액") : null;
        const prepaid = pyStrip(go(r, "기납부")) ? num(rget(r, "기납부"), iss, r, "기납부") : null;
        tax.push({ kind, period, due, amount, state, basis, codes, book, base, calc, prepaid });
      }
    }
  }

  // 장부 채무·정기예금
  const debts = loadDebts(files, iss);
  const manualDep = balances.some((b) => `${b.account} ${b.reason}`.includes("정기예금"));
  const deps = (debts ?? []).filter((x) => x.kind === "정기예금" && x.balance);
  deps.forEach((x, k) => {
    const row = { _file: "장부채무.csv", _line: `정기예금 ${k + 1}` } as Row;
    const bal = x.balance as number;
    if (bal < 0) {
      iss.add(row._file, row._line, `정기예금 ${x.vendor || x.account} 이 올해 ${fmtComma(-bal)}원 줄었는데 분개장에 전기이월이 없어 남은 금액을 모름 → 계좌잔액.csv 확인`);
      return;
    }
    if (manualDep) {
      iss.add(row._file, row._line, `계좌잔액.csv 에 정기예금 줄이 있어 장부 정기예금 ${fmtComma(bal)}원은 넣지 않음`);
      return;
    }
    const due = x.due ? dateParts(x.due) : null;
    if (due === null) {
      iss.add(row._file, row._line, `정기예금 ${x.vendor || x.account} 만기일을 분개장 적요에서 찾지 못함 → 만기일 확인 필요 (쓸 수 없는 돈으로만 둠)`);
    }
    const bdate = dateParts(x.date);
    if (bdate === null) return;
    const guess = Boolean(due && x.due_basis.includes("추정"));
    balances.push({
      date: bdate, account: "정기예금 " + (x.vendor || x.account), bank: x.vendor, balance: bal, restricted: bal,
      reason: `정기예금 (만기 ${due ? due : "확인 필요"}${guess ? " 추정" : ""})`, row, release: due, release_guess: guess,
    });
  });

  // 프로젝트
  const projects: Record<string, Project> = {};
  const project_order: string[] = [];
  for (const r of R("프로젝트.csv")) {
    const pid = g(r, "프로젝트번호");
    if (!pid) {
      iss.add(r._file, r._line, "프로젝트번호 없음 → 제외");
      continue;
    }
    if (has(projects, pid)) {
      iss.add(r._file, r._line, `프로젝트번호 ${pid} 중복 → 뒤의 줄은 제외`);
      continue;
    }
    const name = g(r, "프로젝트명"), team = g(r, "팀") || "팀 미지정", client = g(r, "클라이언트"), state = g(r, "상태");
    const estimate = num(rget(r, "사전견적예산"), iss, r, "사전견적예산");
    const estimate_raw = g(r, "사전견적예산");
    const budget_date = parseDate(rget(r, "예산수정일"), iss, r, "예산수정일");
    const contract = num(rget(r, "계약금액"), iss, r, "계약금액");
    const recognized = num(rget(r, "매출반영누계"), iss, r, "매출반영누계");
    const event_date = g(r, "행사일");
    const quote = num(rget(r, "견적금액"), iss, r, "견적금액");
    const exec_budget = num(rget(r, "실행가"), iss, r, "실행가");
    const approval = gs(r, "승인단계");
    const done_date = parseDate(rget(r, "완료일"), iss, r, "완료일");
    projects[pid] = {
      id: pid, name, team, client, state, estimate, estimate_raw, budget_date, contract, recognized, event_date,
      quote, exec_budget, approval, done_date, row: r,
    };
    project_order.push(pid);
  }

  // 프로젝트집행
  const execs: Exec[] = [];
  const blankProject: Row[] = [];
  for (const r of R("프로젝트집행.csv")) {
    const project = g(r, "프로젝트번호"), item = g(r, "항목"), vendor = g(r, "거래처"), state0 = g(r, "상태");
    const supply = num(rget(r, "공급가액"), iss, r, "공급가액");
    const vat = num(rget(r, "부가세"), iss, r, "부가세");
    const date = parseDate(rget(r, "일자"), iss, r, "일자");
    const e: Exec = { project, item, vendor, state: state0, supply, vat, date, firm: g(r, "확정여부") === "확정", basis: g(r, "근거"), row: r };
    if (!EXEC_STATES.includes(e.state)) {
      iss.add(r._file, r._line, `상태 값 '${e.state}'은(는) 허용 값이 아님 (${EXEC_STATES.join("/")}) → 지급 전(요청미지급)으로 보고 지급 일정에 넣음`);
      e.state = "요청미지급";
    }
    if (e.basis.startsWith("WEHAGO ")) {
      // 장부 원가 줄의 음수는 취소·감액 전표: 부호 그대로
    } else if (INTRANET_IN_FUNDS || !e.basis.startsWith("지급요청")) {
      e.supply = outflow(iss, r, "공급가액", e.supply);
      e.vat = outflow(iss, r, "부가세", e.vat);
    }
    if (isPrior(e)) {
      // 지난해 프로젝트: 알리지 않음
    } else if (!pyStrip(e.project)) {
      blankProject.push(r);
    } else if (!has(projects, e.project)) {
      iss.add(r._file, r._line, `프로젝트번호 '${e.project}'가 프로젝트.csv에 없음 (프로젝트 미연결로 집계)`);
    }
    if (e.state === "집행계획미요청" && !e.basis) iss.add(r._file, r._line, "집행계획미요청 줄에 근거(계약·발주·집행계획) 없음");
    execs.push(e);
  }
  if (blankProject.length) {
    iss.add((blankProject[0] as Row)._file, "-", `프로젝트번호 빈칸 줄 ${blankProject.length}건 → 프로젝트 미연결로 집계 (어느 줄인지는 변환결과.txt [연결])`);
  }

  // 계산서
  const invoices: Invoice[] = [];
  for (const r of R("계산서.csv")) {
    const project = g(r, "프로젝트번호"), client = g(r, "거래처");
    const date = parseDate(rget(r, "발행일"), iss, r, "발행일");
    const kind = g(r, "구분") || "발행";
    const supply = num(rget(r, "공급가액"), iss, r, "공급가액");
    const vat = num(rget(r, "부가세"), iss, r, "부가세");
    const due = parseDate(rget(r, "입금예정일"), iss, r, "입금예정일");
    const due_firm = ["Y", "확정"].includes(g(r, "예정일확정"));
    const paid_date = parseDate(rget(r, "입금일"), iss, r, "입금일");
    const paid = num(rget(r, "입금액"), iss, r, "입금액");
    if (!check(iss, r, "구분", kind, INVOICE_KINDS)) continue;
    if (project && !has(projects, project)) iss.add(r._file, r._line, `프로젝트번호 '${project}'가 프로젝트.csv에 없음`);
    invoices.push({ project, client, date, kind, supply, vat, due, due_firm, paid_date, paid, row: r });
  }

  // 손익
  const pl: PlRow[] = [];
  for (const r of R("손익.csv")) {
    const source = g(r, "출처");
    let ym = Array.from(g(r, "연월").replace(/\./g, "-").replace(/\//g, "-")).slice(0, 7).join("");
    // 새 안전장치: 연월은 글자로 비교하므로 '2026-9' 는 '2026-09' 로 고치고, 그래도 YYYY-MM 이 아니면 알린다
    const ymParts = /^(\d{4})-(\d{1,2})$/.exec(ym);
    if (ymParts) ym = `${ymParts[1]}-${ymParts[2]!.padStart(2, "0")}`;
    else if (ym) iss.add(r._file, r._line, `연월 '${g(r, "연월")}' 형식 확인 (YYYY-MM) → 기간 합계에서 빠질 수 있음`);
    const unit = g(r, "단위"), target = g(r, "대상");
    const revenue = num(rget(r, "매출"), iss, r, "매출");
    const direct = num(rget(r, "직접비"), iss, r, "직접비");
    const common = num(rget(r, "공통비"), iss, r, "공통비");
    const p: PlRow = { source, ym, unit, target, revenue, direct, common, provisional: ["Y", "잠정"].includes(g(r, "잠정")), row: r };
    check(iss, r, "단위", p.unit, ["회사", "팀", "프로젝트"]);
    pl.push(p);
  }

  const plans: PlanRow[] = R("지급계획.csv").map((r) => {
    const week = parseDate(rget(r, "주시작일"), iss, r, "주시작일");
    const project = g(r, "프로젝트번호"), vendor = g(r, "거래처");
    return { week, project, vendor, amount: num(rget(r, "계획금액"), iss, r, "계획금액"), row: r };
  });

  const changes: ChangeRow[] = R("변경내역.csv").map((r) => ({
    date: parseDate(rget(r, "변경일"), iss, r, "변경일"), field: g(r, "항목"), target: g(r, "대상"),
    before: g(r, "변경전"), after: g(r, "변경후"), reason: g(r, "사유"),
  }));

  const asof: AsofRow[] = R("자료기준일.csv").map((r) => ({
    name: g(r, "자료"), date: parseDate(rget(r, "기준일"), iss, r, "기준일"), memo: g(r, "비고"),
  }));

  const diffs: DiffRow[] = R("자료차이.csv").map((r) => {
    const item = g(r, "항목"), a = g(r, "자료A");
    const a_amt = num(rget(r, "금액A"), iss, r, "금액A");
    const b = g(r, "자료B");
    const b_amt = num(rget(r, "금액B"), iss, r, "금액B");
    return { item, a, a_amt, b, b_amt, state: g(r, "상태") };
  });

  return {
    issues: iss, present, out_missing, in_missing, settings, settings_line, book_bank, balances, txns, schedule,
    fundplan, fundplan_problem, fundplan_received, fundplan_received_at, dept, dept_problem, staff, dept_accounts,
    evid_month, accounts, accounts_problem, pay_details: pd ?? [], pay_requests: pr ?? [], team_targets, dep_manual,
    budget_confirmed, tax, debts, projects, project_order, execs, invoices, pl, plans, changes, asof, diffs,
  };
}
