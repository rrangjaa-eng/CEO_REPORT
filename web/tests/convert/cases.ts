// golden 사례의 input/ 폴더 전체를 변환 입력(ConvFiles)으로 읽는다 (시험용, Node 22 fs).
import type { ConvFiles } from "../../src/convert/files";
import { CASES_DIR } from "../calc/golden";

interface NodeFs {
  readFileSync(p: string): Uint8Array;
  readdirSync(p: string): string[];
  statSync(p: string): { isFile(): boolean; isDirectory(): boolean };
  existsSync(p: string): boolean;
}
declare const process: { getBuiltinModule(id: "node:fs"): NodeFs };
const fs = process.getBuiltinModule("node:fs");

function walk(dir: string, rel: string, out: ConvFiles): void {
  for (const name of fs.readdirSync(dir).sort()) {
    const p = dir + "/" + name;
    const r = rel ? rel + "/" + name : name;
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, r, out);
    else if (st.isFile()) out[r] = new Uint8Array(fs.readFileSync(p));
  }
}

/** golden/cases/<id>/input 아래 모든 파일 → '입력/…', '수집/…' 경로. */
export function caseInput(id: string): ConvFiles {
  const out: ConvFiles = {};
  walk(CASES_DIR + id + "/input", "", out);
  return out;
}

export function readFixture(rel: string): Uint8Array {
  return new Uint8Array(fs.readFileSync(decodeURIComponent(new URL("./fixtures/" + rel, import.meta.url).pathname)));
}
