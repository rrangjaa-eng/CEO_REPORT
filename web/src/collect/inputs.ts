// 변환 입력 만들기: 불러온 보고 폴더 파일 + 확장에서 받은 자료(수집/위하고/<파일 이름> JSON 으로) → ConvFiles·수정 시각.
import type { ConvFiles } from "../convert/files";
import type { IsoDate } from "../model/dates";
import type { CollectedDoc } from "./docs";
import type { FolderFile } from "./folder";

const SEOUL_MS = 9 * 3600 * 1000;
const p2 = (n: number) => String(n).padStart(2, "0");

/** 서울 날짜 (YYYY-MM-DD). 이 PC 시간대와 상관없이 UTC 에 9시간을 더해 읽는다. */
export function seoulDate(ms: number): IsoDate {
  return new Date(ms + SEOUL_MS).toISOString().slice(0, 10);
}

/** 서울 시각 'YYYY-MM-DD HH:MM:SS' (변환의 now 모양). */
export function seoulNow(ms: number): string {
  const s = new Date(ms + SEOUL_MS).toISOString();
  return `${s.slice(0, 10)} ${s.slice(11, 19)}`;
}

/** 확장의 수집시각('YYYY-MM-DD HH:MM:SS', 서울 시각) → ms. 못 읽으면 null. */
export function collectedMs(stamp: unknown): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(String(stamp ?? ""));
  if (!m) return null;
  const [, y, mo, d, h, mi, s] = m.map(Number) as number[];
  return Date.UTC(y!, mo! - 1, d!, h!, mi!, s!) - SEOUL_MS;
}

/** 확장 periodTag 와 같은 식 (background.ts). 확장은 저장한 해(지금)로 견주므로 여기서는 수집시각의 해로 견준다. */
function periodTag(kind: string, params: unknown, year: number): string {
  if (kind !== "분개장" || !params || typeof params !== "object") return "";
  const pr = params as Record<string, unknown>;
  const s = String(pr["start_date"] ?? ""), e = String(pr["end_date"] ?? "");
  if (!/^\d{8}$/.test(s) || !/^\d{8}$/.test(e)) return "";
  const ey = e.slice(0, 4);
  if (+ey < year) return `_${ey}` + (s === `${ey}0101` && e === `${ey}1231` ? "" : `_기간${s}-${e}`);
  return s === `${year}0101` ? "" : `_기간${s}-${e}`;
}

const safeName = (s: string) => s.replace(/[\\/:*?"<>|\s]+/g, "");

/** 이름 없이 저장된 자료(이 고침 전에 받은 것)의 파일 이름을 확장과 같은 꼴로 짓는다:
 *  'YYMMDD <종류>[기간 꼬리] 자동수집.json' — YYMMDD 는 수집시각 날짜.
 *  분개장은 확장처럼 기간 꼬리(_2025, _기간YYYYMMDD-YYYYMMDD)를 붙이고, 결산·대조 등 화면 원본은 '<종류에서 원본 뗀 것>_<화면>[_연도]'.
 *  변환은 분개장·자금계획만 읽고 나머지 이름은 쓰지 않는다. */
export function docFileName(doc: CollectedDoc): string {
  const stamp = String(doc.수집시각 ?? "");
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(stamp);
  const ymd6 = m ? `${m[1]!.slice(2)}${m[2]}${m[3]}` : "000000";
  const year = m ? Number(m[1]) : 0;
  let kind = safeName(String(doc.종류));
  if (doc.화면 !== undefined || doc.화면코드 !== undefined) {
    const screen = safeName(String(doc.화면 ?? doc.화면코드 ?? "화면")).replace(/전자세금계산서/g, "전자계산서")
      .replace(/분개장/g, "분개").replace(/자금계획/g, "자금");
    kind = `${kind.replace(/원본$/, "")}_${screen}` + (doc.연도 !== undefined && doc.연도 !== "" ? `_${safeName(String(doc.연도))}` : "");
  }
  return `${ymd6} ${kind}${periodTag(String(doc.종류), doc.기간, year)} 자동수집.json`;
}

/** 받은 자료의 이름: 확장이 준 이름(경로 조각·위험 글자 없이), 없으면 docFileName. */
export function nameOf(doc: CollectedDoc, name?: string | null): string {
  const n = String(name ?? "").replace(/^.*[\\/]/, "").trim();
  return n && n.toLowerCase().endsWith(".json") ? n : docFileName(doc);
}

export interface ExtDoc { doc: CollectedDoc; name?: string | null }

export interface ConvInput {
  files: ConvFiles;
  /** 경로 → 수정 시각(초). 변환이 같은 날짜 자료를 고를 때 쓴다. */
  mtimes: Record<string, number>;
  /** 입력 폴더 파일 → 작성일 (서울). 변환 알림에만 쓴다. */
  fileDays: Record<string, IsoDate>;
  /** 경로 → 어디서 왔는지 */
  from: Record<string, "폴더" | "확장">;
}

const enc = new TextEncoder();

/** 폴더 파일과 확장 자료를 하나로. 같은 경로면 더 새것(폴더 파일은 수정 시각, 확장 자료는 수집시각)이 이긴다. */
export function buildConvInput(folder: FolderFile[], docs: ExtDoc[]): ConvInput {
  const files: ConvFiles = {}, mtimes: Record<string, number> = {}, fileDays: Record<string, IsoDate> = {};
  const from: ConvInput["from"] = {};
  const at = new Map<string, number>();
  const put = (path: string, bytes: Uint8Array, ms: number, src: "폴더" | "확장") => {
    const had = at.get(path);
    if (had !== undefined && had >= ms) return;
    at.set(path, ms);
    files[path] = bytes;
    mtimes[path] = ms / 1000;
    from[path] = src;
    if (path.startsWith("입력/")) fileDays[path] = seoulDate(ms);
  };
  for (const f of folder) put(f.path, f.bytes, f.lastModified, "폴더");
  for (const d of docs) {
    const ms = collectedMs(d.doc.수집시각) ?? 0;
    put(`수집/위하고/${nameOf(d.doc, d.name)}`, enc.encode(JSON.stringify(d.doc)), ms, "확장");
  }
  return { files, mtimes, fileDays, from };
}
