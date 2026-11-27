// 변환 입력 파일 묶음. 파이썬은 폴더(입력·수집·수집/위하고)를 읽지만, 여기서는 '상대 경로 → 바이트' 묶음을 받는다.
// 경로 예: '입력/계산서.csv', '수집/위하고/261031 분개장 자동수집.json', '수집/인트라넷_20261101_180000/프로젝트목록.csv'.
// 구분자는 '/' 하나. 폴더 자체는 항목이 없고, 파일 경로의 앞부분으로 있다고 본다.
import { decodeText, readCsv, type CsvInfo } from "../model/csv";
import type { Issues, Row } from "../model/util";

/** 상대 경로 → 파일 바이트 (CSV·JSON·엑셀 모두 바이트 그대로). */
export type ConvFiles = Record<string, Uint8Array>;

export const INPUT = "입력";
export const COLLECT = "수집";
export const WEHAGO = "수집/위하고";

/** os.path.basename */
export function basename(p: string): string {
  const i = p.lastIndexOf("/");
  return i < 0 ? p : p.slice(i + 1);
}

/** os.path.join(folder, name) */
export function join(folder: string, name: string): string {
  return folder ? folder + "/" + name : name;
}

/** os.listdir(folder) 의 파일만 (하위 폴더 이름은 listDirs). 정렬하지 않은 이름 목록 (파이썬 호출처가 정렬한다). */
export function listFiles(files: ConvFiles, folder: string): string[] {
  const pre = folder + "/";
  const out: string[] = [];
  for (const p of Object.keys(files)) {
    if (p.startsWith(pre) && !p.slice(pre.length).includes("/")) out.push(p.slice(pre.length));
  }
  return out;
}

/** folder 바로 아래 하위 폴더 이름들. */
export function listDirs(files: ConvFiles, folder: string): string[] {
  const pre = folder + "/";
  const out = new Set<string>();
  for (const p of Object.keys(files)) {
    if (!p.startsWith(pre)) continue;
    const rest = p.slice(pre.length);
    const i = rest.indexOf("/");
    if (i > 0) out.add(rest.slice(0, i));
  }
  return [...out];
}

export function exists(files: ConvFiles, path: string): boolean {
  return Object.prototype.hasOwnProperty.call(files, path);
}

/** util.read_text: UTF-8(BOM 떼기) → CP949. 없으면 undefined, 못 읽으면 null. */
export function readText(files: ConvFiles, path: string): string | null | undefined {
  if (!exists(files, path)) return undefined;
  return decodeText(files[path] as Uint8Array);
}

/** UTF-8 만 (json.load(open(path, encoding='utf-8')) 등). BOM 은 keepBom=false 면 뗀다. 못 읽으면 null. */
export function readUtf8(files: ConvFiles, path: string, stripBom = true): string | null {
  const raw = files[path];
  if (raw === undefined) return null;
  try {
    const t = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(raw);
    return stripBom && t.startsWith("﻿") ? t.slice(1) : t;
  } catch {
    return null;
  }
}

/** util.read_text 로 읽은 글 (없으면 undefined). 인코딩을 못 읽으면 undefined 이고 issues 에 파이썬 read_csv 와 같은 알림을 남긴다. */
export function decodeTextOr(files: ConvFiles, path: string, issues?: Issues, name?: string): string | undefined {
  if (!exists(files, path)) return undefined;
  const t = decodeText(files[path] as Uint8Array);
  if (t === null) {
    issues?.add(name ?? basename(path), "-", "글자 인코딩을 읽지 못함 (UTF-8 또는 CP949로 저장 필요)");
    return undefined;
  }
  return t;
}

/** util.read_csv(path, required, issues, info) — 파일 없음·인코딩 실패까지 파이썬과 같게. */
export function readCsvFile(files: ConvFiles, path: string, required: readonly string[], issues: Issues, info?: CsvInfo): [Row[], boolean] {
  const name = basename(path);
  if (!exists(files, path)) return readCsv(name, undefined, required, issues, info);
  const t = decodeText(files[path] as Uint8Array);
  if (t === null) {
    if (info) info.missing = [...required];
    issues.add(name, "-", "글자 인코딩을 읽지 못함 (UTF-8 또는 CP949로 저장 필요)");
    return [[], false];
  }
  return readCsv(name, t, required, issues, info);
}
