// wehago_raw.py(files·asset_rows 등 읽기 부분)와 screen_tax.py: 위하고 화면 원본(.json) 읽기.
import type { IsoDate } from "../model/dates";
import { ymd } from "../model/dates";
import { cmpStr, fmtComma, pyFloatParse, pyIntParse, pyRemoveSpace, pyStrip, sortedBy } from "../model/py";
import { join, listFiles, readUtf8, type ConvFiles } from "./files";
import { isDict, pyStrJ, pyStrOr } from "./pyjson";
import type { JLine } from "./wehago";

type J = unknown;
type D = Record<string, J>;

/** wehago_raw._num */
export function rawNum(v: J): number {
  const t = pyStrip(pyStrJ(v).replaceAll(",", ""));
  const f = pyFloatParse(t || "0");
  if (f === null || !Number.isFinite(f)) return 0;
  return Math.trunc(f);
}

export function rawDate(t: J): string {
  const s = pyStrOr(t).replace(/\D/gu, "");
  if (s.length !== 8) return "";
  try {
    return ymd(Number(s.slice(0, 4)), Number(s.slice(4, 6)), Number(s.slice(6)));
  } catch {
    return "";
  }
}

const YEARLESS = ["인사_사원등록"];
const NEED: Record<string, string> = { SACL0105: "/sacl0105/main$", SACL0108: "/sacl0108/plusforw$", SAAS0107: "/allfixlist$",
  SWPM0108: "/swpm0108/condition$", SWSA0105: "/swsa0105/total$", SWBU0103: "/swbu0103/tab1$",
  SWET0107: "/swet0107/other/tab01$", SWYM0107: "/emp/income$", SWYM0102: "/swym0102$",
  SACL0104: "/sacl0104/account$", SAFM0109: "/safm0109$", SAFM0107: "/safm0107/balance/statement$",
  SACL0106: "/sacl0106/0", SAAC0103: "/saac0103/jungsang$", SAFM0108: "/safm0108/\\d+$",
  SABM0109: "/sabm0109/bsflist", SAAC0110: "/collectingdata/", SAVF0119: "/savf0119/top$",
  SWTA0101: "/swta0101/sglist$" };

export function isError(data: J): boolean {
  if (!isDict(data)) return false;
  const st = data["status"];
  if (typeof st === "number" && Number.isInteger(st) && st >= 400) return true;
  return typeof data["error"] === "string" && !!data["error"] && "status" in data;
}

const resps = (d: D): D[] => (Array.isArray(d["응답"]) ? (d["응답"] as J[]) : []).filter(isDict) as D[];
const rstripSlash = (s: string) => s.replace(/\/+$/, "");

export function hasData(d: D): boolean {
  const codeS = pyStrOr(d["화면코드"]).toUpperCase();
  const need = Object.prototype.hasOwnProperty.call(NEED, codeS) ? new RegExp(NEED[codeS]!) : null;
  for (const r of resps(d)) {
    if (isError(r["data"])) continue;
    if (need === null || need.test(rstripSlash(pyStrOr(r["path"])).toLowerCase())) return true;
  }
  return false;
}

export type RawFiles = Map<string, { screen: string; year: number; stamp: string; path: string; d: D }>;

function loadJson(files: ConvFiles, path: string): J | undefined {
  const text = readUtf8(files, path, false);
  if (text === null || text.startsWith("﻿")) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/** wehago_raw.files */
export function rawFiles(files: ConvFiles, wehagoDir: string, skipped?: string[]): RawFiles {
  const out: RawFiles = new Map();
  for (const n of listFiles(files, wehagoDir).sort(cmpStr)) {
    if (!n.endsWith("자동수집.json") || n.includes("분개장") || n.includes("자금계획")) continue;
    const path = join(wehagoDir, n);
    const d = loadJson(files, path);
    if (d === undefined) { skipped?.push(n); continue; }
    if (!isDict(d) || !("응답" in d)) continue;
    if (!hasData(d)) { skipped?.push(n); continue; }
    const kind = pyStrOr(d["종류"]).replaceAll("원본", "");
    const screen = `${kind}_${pyStrOr(d["화면"])}`;
    const yt = pyStrip(pyStrJ(pyStrOr(d["연도"]) || 0)).slice(0, 4);
    let year = yt ? pyIntParse(yt) : 0;
    if (year === null) year = 0;
    if (year < 2000 && !YEARLESS.includes(screen)) continue;
    const key = screen + "\u0000" + year;
    const stamp = pyStrOr(d["수집시각"]) + n;
    if (!out.has(key) || cmpStr(out.get(key)!.stamp, stamp) < 0) out.set(key, { screen, year, stamp, path, d });
  }
  return out;
}

export function rawResp(d: D, tail: string): J {
  for (const r of resps(d)) {
    if (rstripSlash(pyStrOr(r["path"])).endsWith(rstripSlash(tail))) return r["data"] ?? null;
  }
  return null;
}

export function rawPick(F: RawFiles, screen: string, year: number | null = null): [number, D][] {
  const got: [number, D][] = [...F.values()].filter((v) => v.screen === screen && (year === null || v.year === year)).map((v) => [v.year, v.d]);
  return sortedBy(got, (t) => -t[0]);
}

export function rawFind(x: J, key: string, depth = 0): J {
  if (depth > 4) return null;
  if (isDict(x)) {
    if (key in x) return x[key];
    for (const v of Object.values(x)) {
      const got = rawFind(v, key, depth + 1);
      if (got !== null && got !== undefined) return got;
    }
  } else if (Array.isArray(x)) {
    for (const v of x.slice(0, 3)) {
      const got = rawFind(v, key, depth + 1);
      if (got !== null && got !== undefined) return got;
    }
  }
  return null;
}

/** wehago_raw.asset_rows */
export function assetRows(F: RawFiles): Record<string, string>[] {
  const rows: Record<string, string>[] = [];
  for (const [year, d] of rawPick(F, "결산_고정자산관리대장").slice(0, 1)) {
    const list = rawResp(d, "/allfixlist");
    for (const a of (Array.isArray(list) ? list : []) as J[]) {
      if (!isDict(a) || !(a["cd_fixast"] !== null && a["cd_fixast"] !== undefined && a["cd_fixast"] !== "" && a["cd_fixast"] !== 0 && a["cd_fixast"] !== false)) continue;
      rows.push({ "기준연도": String(year), "자산": pyStrip(pyStrOr(a["nm_fixast"])), "계정": pyStrOr(a["nm_acctit"]),
        "취득일": rawDate(a["da_acquire"]), "취득가": String(rawNum(a["mn_base"]) + rawNum(a["mn_new"])),
        "상각률": pyStrOr(a["rt_depre"]), "전기말상각누계": String(rawNum(a["mn_ftdepsum"])), "당기상각": String(rawNum(a["mn_ctdepre1"])),
        "당기말상각누계": String(rawNum(a["mn_ctdepsum"])) });
    }
  }
  return rows;
}

// ───────────── screen_tax ─────────────
const KINDS = ["근로", "사업", "기타"] as const;
const GAP_WARN = 100000;
type YM = string;   // "연-월"

function ymOf(v: J): [number, number] | null {
  const t = pyStrOr(v).replace(/\D/gu, "");
  return t.length >= 6 ? [Number(t.slice(0, 4)), Number(t.slice(4, 6))] : null;
}

function rowsOf(data: J, key: string): D[] {
  const got = isDict(data) || Array.isArray(data) ? rawFind(data, key) : null;
  return Array.isArray(got) ? (got.filter(isDict) as D[]) : [];
}

export function incomeTax(F: RawFiles): Map<YM, Record<string, number>> {
  const out = new Map<YM, Record<string, number>>();
  const add = (ym: [number, number] | null, kind: string, v: number) => {
    if (ym && v) {
      const k = `${ym[0]}-${ym[1]}`;
      if (!out.has(k)) out.set(k, { "근로": 0, "사업": 0, "기타": 0 });
      out.get(k)![kind]! += v;
    }
  };
  const seen = new Set<string>();
  for (const [, d] of rawPick(F, "인사_소득자별근로소득원천징수부")) {
    for (const r of resps(d)) {
      if (!rstripSlash(pyStrOr(r["path"])).endsWith("/emp/income")) continue;
      const data = r["data"];
      const codeV = pyTruthy(r["cd_emp"]) ? r["cd_emp"] : rawFind(data, "cd_emp");
      for (const g of rowsOf(data, "group1")) {
        const ym = ymOf(pyTruthy(g["ym_rvrs"]) ? g["ym_rvrs"] : g["ym_pay"]);
        const key = pyStrJ(codeV) + "\u0000" + (ym ? ym.join("-") : "");
        if (!pyTruthy(codeV) || ym === null || seen.has(key)) continue;
        seen.add(key);
        add(ym, "근로", rawNum(g["am_income1"]) + rawNum(g["am_inhabit1"]));
      }
    }
  }
  for (const [screen, tail, key, kind] of [["인사_사업소득조회", "/swbu0103/tab1", "tab1_up", "사업"], ["인사_기타소득조회", "/swet0107/other/tab01", "data", "기타"]] as const) {
    const years = new Set<number>();
    for (const [year, d] of rawPick(F, screen)) {
      if (years.has(year)) continue;
      years.add(year);
      const data = rawResp(d, tail);
      for (const r of rowsOf(data, key)) add(ymOf(pyTruthy(r["ym_pay"]) ? r["ym_pay"] : r["ym_rvrs"]), kind, rawNum(r["am_income"]) + rawNum(r["am_inhabit"]));
    }
  }
  return out;
}

function pyTruthy(v: J): boolean {
  if (v === null || v === undefined || v === false || v === 0 || v === "") return false;
  if (Array.isArray(v)) return v.length > 0;
  if (isDict(v)) return Object.keys(v).length > 0;
  return true;
}

export function employeeInsurance(F: RawFiles, wageTax: Map<YM, Record<string, number>>): Map<YM, number> {
  const ded = new Map<YM, number>();
  for (const [year, d] of rawPick(F, "인사_월별급상여수당지급현황")) {
    const list = rawResp(d, "/total");
    for (const r of (Array.isArray(list) ? list : []).filter(isDict) as D[]) {
      if (!pyStrip(pyStrOr(r["nm_krname"])) || (pyTruthy(r["cd_code"]) && pyTruthy(r["cd_emp"]) && r["cd_code"] !== r["cd_emp"])) continue;
      for (let m = 1; m <= 12; m++) {
        const v = rawNum(r[`mon_${String(m).padStart(2, "0")}_gong`]);
        if (v) ded.set(`${year}-${m}`, (ded.get(`${year}-${m}`) ?? 0) + v);
      }
    }
  }
  return new Map([...ded].map(([k, v]) => [k, v - (wageTax.get(k)?.["근로"] ?? 0)]));
}

function book(journal: JLine[], codes: string[], vendors: string[]): Map<YM, number> {
  const cs = new Set(codes.map((c) => pyRemoveSpace(String(c))));
  const out = new Map<YM, number>();
  for (const ln of journal) {
    if (ln.date === null || !cs.has(pyRemoveSpace(String(ln.account_code || "")))) continue;
    if (!vendors.some((v) => pyRemoveSpace(String(ln.vendor || "")).includes(v))) continue;
    const k = `${Number(ln.date.slice(0, 4))}-${Number(ln.date.slice(5, 7))}`;
    out.set(k, (out.get(k) ?? 0) + (ln.credit || 0));
  }
  return out;
}

function signedComma(n: number): string {
  return (n >= 0 ? "+" : "") + fmtComma(n);
}

/** screen_tax.compare -> [notes, 원천세 화면 달별 합] */
export function compareScreens(journal: JLine[], F: RawFiles, asof: IsoDate, whCodes: string[] = ["25400"],
  whVendors: string[] = ["세무서", "구청", "시청", "군청"], insVendors: string[] = ["국민연금", "건강보험", "근로복지", "고용보험"]): [string[], Map<YM, number>] {
  const tax = incomeTax(F);
  if (!tax.size) return [[], new Map()];
  const totals = new Map([...tax].map(([k, v]) => [k, KINDS.reduce((a, kk) => a + v[kk]!, 0)]));
  const bookWh = book(journal, whCodes, whVendors), bookIns = book(journal, whCodes, insVendors);
  const ins = employeeInsurance(F, tax);
  const y = Number(asof.slice(0, 4)), mm = Number(asof.slice(5, 7));
  const months: YM[] = [];
  for (let m = 1; m <= mm; m++) months.push(`${y}-${m}`);
  const gaps: string[] = [], igaps: string[] = [];
  for (const ym of months) {
    const mo = ym.split("-")[1];
    if (totals.has(ym) && bookWh.has(ym) && Math.abs(bookWh.get(ym)! - totals.get(ym)!) > GAP_WARN) {
      gaps.push(`${mo}월 장부 ${fmtComma(bookWh.get(ym)!)} · 화면 ${fmtComma(totals.get(ym)!)} (근로 ${fmtComma(tax.get(ym)!["근로"]!)}·사업 ${fmtComma(tax.get(ym)!["사업"]!)}·기타 ${fmtComma(tax.get(ym)!["기타"]!)})`);
    }
    if (ins.has(ym) && bookIns.has(ym) && Math.abs(bookIns.get(ym)! - ins.get(ym)!) > GAP_WARN) {
      igaps.push(`${mo}월 장부 ${fmtComma(bookIns.get(ym)!)} · 화면 ${fmtComma(ins.get(ym)!)}`);
    }
  }
  const have = months.filter((ym) => totals.has(ym) && bookWh.has(ym));
  const sb = have.reduce((a, k) => a + bookWh.get(k)!, 0), sw = have.reduce((a, k) => a + totals.get(k)!, 0);
  const notes = [`원천세 장부↔위하고 화면(근로 원천징수부+사업소득+기타소득) ${y}년 ${have.length}개월: 장부 ${fmtComma(sb)} · 화면 ${fmtComma(sw)} (차이 ${signedComma(sb - sw)})`];
  if (gaps.length) notes.push(`[확인] 원천세 장부·위하고 화면이 10만 원 넘게 다른 달: ${gaps.join(" / ")} — 연말정산 정산분·퇴직소득세·지급월 차이인지 확인`);
  if (igaps.length) notes.push(`[확인] 4대보험 직원분 장부·위하고 급여 화면(공제합계−소득세·지방소득세)이 10만 원 넘게 다른 달: ${igaps.join(" / ")} — 화면 쪽에 다른 공제(가불 등)가 있으면 그만큼 큼`);
  return [notes, totals];
}

const CARD_SCREEN = "SAAC0105";
const CARD_PATH = /\/saac0105\/\p{Nd}+\/?$/iu;

/** json.dumps(sort_keys=True) 비슷한 같은 응답 열쇠 (같은 응답 두 번 세지 않게). */
function stableJson(v: J): string {
  if (Array.isArray(v)) return "[" + v.map(stableJson).join(",") + "]";
  if (isDict(v)) return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + stableJson(v[k])).join(",") + "}";
  return JSON.stringify(v ?? null);
}

/** screen_tax.card_usage -> [카드 사용, 자료 끝 날짜] */
export function cardUsage(files: ConvFiles, wehagoDir: string): [Map<string, [IsoDate, number][]>, IsoDate | null] {
  let best: [string, D] | null = null;
  for (const n of listFiles(files, wehagoDir).sort(cmpStr)) {
    if (!n.endsWith(".json") || n.includes("분개장") || n.includes("자금계획")) continue;
    const d = loadJson(files, join(wehagoDir, n));
    if (d === undefined) continue;
    if (!isDict(d) || pyStrOr(d["화면코드"]).toUpperCase() !== CARD_SCREEN) continue;
    const stamp = pyStrOr(d["수집시각"]).replace(/\D/gu, "");
    if (best === null || cmpStr(stamp, best[0]) > 0) best = [stamp, d];
  }
  if (best === null) return [new Map(), null];
  const out = new Map<string, [IsoDate, number][]>();
  let last: IsoDate | null = null;
  const seen = new Set<string>();
  for (const r of resps(best[1])) {
    const data = r["data"];
    if (!CARD_PATH.test(pyStrOr(r["path"])) || !isDict(data)) continue;
    const key = rstripSlash(pyStrOr(r["path"])) + "\u0000" + stableJson(data);
    if (seen.has(key)) continue;
    seen.add(key);
    const items = Array.isArray(data["data"]) ? (data["data"] as J[]) : [];
    for (const it of items.filter(isDict) as D[]) {
      const t = pyStrOr(it["da_sbook"]).replace(/\D/gu, "").slice(0, 8);
      let day: IsoDate;
      try {
        day = ymd(Number(t.slice(0, 4)) || 0, Number(t.slice(4, 6)) || 0, Number(t.slice(6, 8)) || 0);
      } catch {
        continue;
      }
      const amt = rawNum(it["mn_total"]);
      const name = pyStrip(pyStrOr(it["nm_ctrade"]).replace(/^\[[^\]]*\]/u, ""));
      const code = pyStrip(pyStrOr(it["cd_ctrade"])).replace(/^0+/, "");
      for (const k of [code ? "code:" + code : null, name || null]) {
        if (k) {
          if (!out.has(k)) out.set(k, []);
          out.get(k)!.push([day, amt]);
        }
      }
      if (last === null || day > last) last = day;
    }
  }
  const s = best[0];
  let upto: IsoDate | null;
  try {
    upto = ymd(Number(s.slice(0, 4)) || 0, Number(s.slice(4, 6)) || 0, Number(s.slice(6, 8)) || 0);
  } catch {
    upto = last;
  }
  return [out, upto];
}
