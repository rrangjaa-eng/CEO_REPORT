// 변환 golden 비교 도구: 범위 밖 줄 빼기 목록, 기대 CSV 글, 결과 비교.
import { writeCsv } from "../../src/model/csv";
import { IN_SCOPE, SIDE_FILES, type ConvertResult } from "../../src/convert/run";
import type { ConvFiles } from "../../src/convert/files";
import type { ConvertExpected } from "../calc/golden";

/** 범위 밖 표 (이 판이 만들지 않음). */
export const OUT_TABLES = ["위하고대조", "연간자료", "현금흐름", "계정잔액", "사원", "급여명세", "연말정산", "고정자산", "잉여금", "세무조정",
  "신고일정", "신고도우미", "자료대조", "차입금", "카드사용"];

/** 화면 줄 중 비교에서 빼는 것: 무늬 + 까닭. 기대값·결과 양쪽에서 같이 뺀다. */
export const EXCLUDED_LINES: { pattern: RegExp; reason: string }[] = [
  { pattern: new RegExp(`^(${OUT_TABLES.join("|")})\\.csv 만듦 \\d+줄$`), reason: "범위 밖 표를 만든 줄" },
  { pattern: new RegExp(`^\\[(${OUT_TABLES.join("|")})\\.csv\\] 만들지 않음 — `), reason: "범위 밖 표를 만들지 않은 줄" },
  { pattern: /^대조 (불일치|판단 불가) \d+건$/, reason: "건수에 범위 밖 표(위하고대조·연간자료 등)와 위하고대조 파일 사이 대조가 섞임 — 대신 범위 안 건수 ≤ 기대 건수를 따로 봄" },
  { pattern: /^홈택스 /, reason: "홈택스 전자세금계산서 대조(hometax.compare)는 범위 밖" },
  { pattern: /^거래처 계좌 목록/, reason: "이체용 거래처 등록(transfer.register_vendors)은 범위 밖" },
  { pattern: /^(지급 요청서|최근 인트라넷 수집에 지급 요청서|경고: 최근 수집의 지급 요청서)/, reason: "지급요청서.csv 옮기기(payreq.write)는 옮기지 않음" },
  { pattern: /^경고: (자동분석|확인할것)\.json/, reason: "자동분석·확인할것 저장은 범위 밖" },
];

export function excluded(line: string): boolean {
  return EXCLUDED_LINES.some((e) => e.pattern.test(line));
}

const OUT_RE = new RegExp(`^(${OUT_TABLES.join("|")})\\.csv$`);

/** 비교용으로 고친 줄: 임시 폴더 경로를 떼고, '이전 파일' 목록에서 범위 밖 표 이름을 뺀다. */
export function normLine(line: string): string {
  line = line.replace(/^대조 내용: .*[\\/]입력[\\/]변환결과\.txt$/, "대조 내용: 입력/변환결과.txt");
  const m = /^이전 파일: (\S+) \((.*)\)$/.exec(line);
  if (m) line = `이전 파일: ${m[1]} (${(m[2] as string).split(", ").filter((n) => !OUT_RE.test(n)).join(", ")})`;
  return line;
}

export function compareLines(want: string[], got: string[]): string[] {
  const w = want.filter((l) => !excluded(l)).map(normLine);
  const g = got.filter((l) => !excluded(l)).map(normLine);
  const out: string[] = [];
  const n = Math.max(w.length, g.length);
  for (let i = 0; i < n && out.length < 10; i++) {
    if (w[i] !== g[i]) out.push(`줄 ${i}: 기대 ${JSON.stringify(w[i])}\n        실제 ${JSON.stringify(g[i])}`);
  }
  return out;
}

const count = (lines: string[], re: RegExp) => Number(lines.map((l) => re.exec(l)?.[1]).find((x) => x !== undefined) ?? 0);

/** 범위 안 대조 불일치·판단 불가 건수는 기대 건수(범위 밖 포함)를 넘지 않아야 한다. */
export function countProblems(want: string[], got: string[]): string[] {
  const out: string[] = [];
  for (const re of [/^대조 불일치 (\d+)건$/, /^대조 판단 불가 (\d+)건$/]) {
    if (count(got, re) > count(want, re)) out.push(`${re.source}: 기대 ${count(want, re)} < 실제 ${count(got, re)}`);
  }
  return out;
}

/** 파일 비교: 기대에 있는 범위 안 CSV 는 글자까지 같고, 기대에 없는데 만든 CSV 는 입력 파일과 같아야 한다 (바뀌지 않음). */
export function compareFiles(exp: ConvertExpected, got: ConvertResult, input: ConvFiles): string[] {
  const scope = [...IN_SCOPE, ...SIDE_FILES];
  const out: string[] = [];
  const dec = new TextDecoder("utf-8", { ignoreBOM: true });
  const enc = new TextEncoder();
  for (const name of scope) {
    const want = exp.files[name];
    const g = got.files[name];
    if (want !== undefined) {
      if (g === undefined) out.push(`${name}: 만들지 않음 (기대에 있음)`);
      else if (g !== "﻿" + writeCsv(want)) out.push(`${name}: 글이 다름\n${firstDiff("﻿" + writeCsv(want), g)}`);
    } else if (g !== undefined) {
      const before = input["입력/" + name];
      const same = before !== undefined && before.length === enc.encode(g).length && enc.encode(g).every((x, i) => x === before[i]);
      if (!same) out.push(`${name}: 기대에는 바뀌지 않았는데 다르게 만듦\n${firstDiff(before ? dec.decode(before) : "", g)}`);
    }
  }
  return out;
}

function firstDiff(a: string, b: string): string {
  const al = a.split("\r\n"), bl = b.split("\r\n");
  for (let i = 0; i < Math.max(al.length, bl.length); i++) {
    if (al[i] !== bl[i]) return `   ${i}번째 줄\n   기대 ${JSON.stringify(al[i])}\n   실제 ${JSON.stringify(bl[i])}`;
  }
  return "";
}
