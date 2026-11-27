// golden 사례 읽기 (시험용): input/입력 + expected/convert.json 의 변환 결과로 덮은 파일 묶음, 기대값, 차이 경로.
// @types/node 가 없으므로 Node 22 의 process.getBuiltinModule 로 fs 를 얻는다.
import { decodeText, writeCsv, type FileSet } from "../../src/model/csv";

interface NodeFs {
  readFileSync(p: string): Uint8Array;
  readFileSync(p: string, enc: "utf8"): string;
  readdirSync(p: string): string[];
  existsSync(p: string): boolean;
  statSync(p: string): { isFile(): boolean };
}
declare const process: { getBuiltinModule(id: "node:fs"): NodeFs };
const fs = process.getBuiltinModule("node:fs");

export const CASES_DIR = decodeURIComponent(new URL("../../../golden/cases/", import.meta.url).pathname);

export interface CaseInfo {
  id: string;
  title: string;
  rules: string[];
  asof: string;
  kinds: ("weekly" | "monthly")[];
  payday?: string | null;
}

export interface ConvertExpected {
  code: number;
  lines: string[];
  files: Record<string, string[][]>;
  json: Record<string, unknown>;
}

export interface KindExpected {
  rc: number;
  stop: string[] | null;
  said: string[];
  R: Record<string, unknown> | null;
}

export interface GoldenCase {
  case: CaseInfo;
  files: FileSet;
  expected: { convert: ConvertExpected; weekly?: KindExpected; monthly?: KindExpected };
}

function readJson<T>(p: string): T {
  return JSON.parse(fs.readFileSync(p, "utf8")) as T;
}

export function listCases(): string[] {
  return fs.readdirSync(CASES_DIR).filter((n) => fs.existsSync(CASES_DIR + n + "/case.json")).sort();
}

/** 입력 폴더 글 (변환 전). 글자로 읽을 수 없는 파일(엑셀 등)은 넣지 않는다. */
export function readInputDir(dir: string): FileSet {
  const files: FileSet = {};
  if (!fs.existsSync(dir)) return files;
  for (const name of fs.readdirSync(dir).sort()) {
    const p = dir + "/" + name;
    if (!fs.statSync(p).isFile()) continue;
    if (!/\.(csv|json|txt)$/i.test(name)) continue;
    const t = decodeText(fs.readFileSync(p));
    if (t !== null) files[name] = t;
  }
  return files;
}

export function loadCase(id: string): GoldenCase {
  const dir = CASES_DIR + id;
  const info = readJson<CaseInfo>(dir + "/case.json");
  const files = readInputDir(dir + "/input/입력");
  const convert = readJson<ConvertExpected>(dir + "/expected/convert.json");
  for (const [name, rows] of Object.entries(convert.files)) files[name] = writeCsv(rows);
  for (const [name, obj] of Object.entries(convert.json)) files[name] = JSON.stringify(obj, null, 1);
  const expected: GoldenCase["expected"] = { convert };
  for (const kind of ["weekly", "monthly"] as const) {
    const p = `${dir}/expected/${kind}.json`;
    if (fs.existsSync(p)) expected[kind] = readJson<KindExpected>(p);
  }
  return { case: info, files, expected };
}

function show(v: unknown): string {
  const s = JSON.stringify(v);
  return s === undefined ? "undefined" : s.length > 120 ? s.slice(0, 117) + "..." : s;
}

/** 깊은 비교: 다른 곳의 경로와 값 (최대 limit 개). 같으면 []. */
export function diffPaths(want: unknown, got: unknown, limit = 20): string[] {
  const out: string[] = [];
  const walk = (w: unknown, g: unknown, path: string): void => {
    if (out.length >= limit) return;
    if (Object.is(w, g)) return;
    if (typeof w === "number" && typeof g === "number" && w === g) return;
    if (Array.isArray(w) && Array.isArray(g)) {
      if (w.length !== g.length) out.push(`${path || "$"}: 길이 기대 ${w.length} 실제 ${g.length}`);
      const n = Math.min(w.length, g.length);
      for (let i = 0; i < n; i++) walk(w[i], g[i], `${path}[${i}]`);
      return;
    }
    if (w && g && typeof w === "object" && typeof g === "object" && !Array.isArray(w) && !Array.isArray(g)) {
      const wo = w as Record<string, unknown>, go = g as Record<string, unknown>;
      const keys = [...new Set([...Object.keys(wo), ...Object.keys(go)])].sort();
      for (const k of keys) {
        const p = `${path}.${k}`;
        if (!(k in go)) { if (out.length < limit) out.push(`${p}: 실제에 없음 (기대 ${show(wo[k])})`); continue; }
        if (!(k in wo)) { if (out.length < limit) out.push(`${p}: 기대에 없음 (실제 ${show(go[k])})`); continue; }
        walk(wo[k], go[k], p);
      }
      return;
    }
    out.push(`${path || "$"}: 기대 ${show(w)} 실제 ${show(g)}`);
  };
  walk(want, got, "");
  return out;
}
