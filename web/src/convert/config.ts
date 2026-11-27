// convert.read_config: 설정.csv 의 '변환_*' 항목 → 변환 설정 (없거나 틀리면 기본값 + 알림).
import { pyStrip } from "../model/py";
import { Issues, isBlank } from "../model/util";
import { exists, join, readCsvFile, type ConvFiles } from "./files";

export interface Cfg {
  revenue_codes: string[]; receivable_codes: string[]; direct_prefixes: string[]; direct_mark: string; common_prefixes: string[];
  common_mark: string; payable_codes: string[]; cash_codes: string[]; loan_codes: string[]; deposit_codes: string[]; vat_codes: string[];
  closing_sorts: string[]; link_days: number; card_words: string[]; snapshot_days: number; salary_codes: string[];
  nonop_in_codes: string[]; nonop_out_codes: string[]; vat_payable_codes: string[]; withholding_codes: string[];
  withholding_vendors: string[]; insurance_vendors: string[]; salary_pay_day: number; withholding_mode: string;
  from_file: boolean;
}

export function defaultConfig(): Cfg {
  return {
    revenue_codes: ["41200"], receivable_codes: ["10800"], direct_prefixes: ["6"], direct_mark: "(도)", common_prefixes: ["8"],
    common_mark: "(판)", payable_codes: ["25300", "26200"], cash_codes: ["10300"], loan_codes: ["26000", "29300"],
    deposit_codes: ["10500"], vat_codes: ["13500"], closing_sorts: ["결차", "결대", "결산전표", "잉여금관련전표"], link_days: 90,
    card_words: ["카드"], snapshot_days: 7, salary_codes: ["80200"], nonop_in_codes: ["90100", "92200", "93000"],
    nonop_out_codes: ["93100", "96000"], vat_payable_codes: ["25500"], withholding_codes: ["25400"],
    withholding_vendors: ["세무서", "구청", "시청", "군청"], insurance_vendors: ["국민연금", "건강보험", "근로복지", "고용보험"],
    salary_pay_day: 5, withholding_mode: "자동", from_file: false,
  };
}

type Kind = "숫자목록" | "낱말" | "낱말목록" | "정수" | "일수";
const ITEMS: [string, keyof Cfg, Kind][] = [
  ["변환_매출계정", "revenue_codes", "숫자목록"], ["변환_매출채권계정", "receivable_codes", "숫자목록"],
  ["변환_직접비코드", "direct_prefixes", "숫자목록"], ["변환_직접비표시", "direct_mark", "낱말"],
  ["변환_공통비코드", "common_prefixes", "숫자목록"], ["변환_공통비표시", "common_mark", "낱말"],
  ["변환_미지급계정", "payable_codes", "숫자목록"], ["변환_현금계정", "cash_codes", "숫자목록"],
  ["변환_차입금계정", "loan_codes", "숫자목록"], ["변환_정기예금계정", "deposit_codes", "숫자목록"],
  ["변환_부가세대급금계정", "vat_codes", "숫자목록"], ["변환_결산구분", "closing_sorts", "낱말목록"],
  ["변환_자동연결일수", "link_days", "일수"], ["변환_카드거래처", "card_words", "낱말목록"],
  ["변환_스냅숏경과일", "snapshot_days", "일수"], ["변환_급여계정", "salary_codes", "숫자목록"],
  ["변환_영업외수익계정", "nonop_in_codes", "숫자목록"], ["변환_영업외비용계정", "nonop_out_codes", "숫자목록"],
  ["변환_부가세예수금계정", "vat_payable_codes", "숫자목록"], ["변환_예수금계정", "withholding_codes", "숫자목록"],
  ["변환_원천세거래처", "withholding_vendors", "낱말목록"], ["변환_원천세납부", "withholding_mode", "낱말"],
  ["변환_4대보험거래처", "insurance_vendors", "낱말목록"], ["변환_급여일", "salary_pay_day", "정수"],
];
export const DAY_RANGE: [number, number] = [1, 3650];

function split(raw: string): string[] {
  return raw.split(",").map((x) => pyStrip(x)).filter((x) => x);
}

function parseValue(kind: Kind, raw: string): string | number | string[] | null {
  const text = pyStrip(raw);
  if (kind === "낱말") return text || null;
  if (kind === "정수" || kind === "일수") return /^[0-9]+$/.test(text) ? Number(text) : null;
  const items = split(text);
  if (!items.length) return null;
  if (kind === "숫자목록" && !items.every((x) => /^[0-9]+$/.test(x))) return null;
  return items;
}

function cfgText(v: unknown): string {
  return Array.isArray(v) ? v.join(",") : String(v);
}

/** read_config(input_dir) → [cfg, notes] */
export function readConfig(files: ConvFiles, inputDir: string): [Cfg, string[]] {
  const cfg = defaultConfig();
  const dflt = defaultConfig();
  const path = join(inputDir, "설정.csv");
  if (!exists(files, path)) return [cfg, ["설정.csv 없음 → 변환 설정 기본값 사용"]];
  const info: { missing?: string[] } = {};
  const [rows, ok] = readCsvFile(files, path, ["항목", "값"], new Issues(), info);
  if (!ok || (info.missing && info.missing.length)) return [cfg, ["설정.csv를 읽지 못함 → 변환 설정 기본값 사용"]];
  const found = new Map<string, string>();
  for (const r of rows) {
    const item = String(r["항목"] ?? "");
    if (item.startsWith("변환_")) {
      found.delete(item);   // OrderedDict 는 같은 열쇠를 덮어도 처음 자리를 지킨다 → 아래에서 처음 자리 유지
      found.set(item, String(r["값"] ?? ""));
    }
  }
  // OrderedDict 순서: 처음 나온 자리. delete+set 은 뒤로 보내므로 처음 자리 순서를 따로 만든다
  const order: string[] = [];
  for (const r of rows) {
    const item = String(r["항목"] ?? "");
    if (item.startsWith("변환_") && !order.includes(item)) order.push(item);
  }
  const notes: string[] = [];
  const known = new Map(ITEMS.map(([item, key, kind]) => [item, [key, kind] as const]));
  for (const item of order) {
    const raw = found.get(item) as string;
    if (!known.has(item)) { notes.push(`설정 ${item} 알 수 없는 변환 항목 → 무시`); continue; }
    const [key, kind] = known.get(item)!;
    const d = cfgText(dflt[key]);
    if (isBlank(raw)) { notes.push(`설정 ${item} 비어 있음 → 기본값 ${d}`); continue; }
    let value = parseValue(kind, raw);
    if (value === null) { notes.push(`설정 ${item} 값 '${raw}' 사용할 수 없음 → 기본값 ${d}`); continue; }
    if (kind === "일수" && typeof value === "number" && !(DAY_RANGE[0] <= value && value <= DAY_RANGE[1])) {
      const fixed = Math.min(Math.max(value, DAY_RANGE[0]), DAY_RANGE[1]);
      notes.push(`설정 ${item} 값 ${value} 범위 밖 (${DAY_RANGE[0]}~${DAY_RANGE[1]}) → ${fixed} 사용`);
      value = fixed;
    }
    (cfg as unknown as Record<string, unknown>)[key] = value;
  }
  cfg.from_file = found.size > 0;
  return [cfg, notes];
}
