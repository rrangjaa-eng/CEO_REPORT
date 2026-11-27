// convert.closing_pl_line · drop_closing_pl: 결산 전표의 손익 줄 처리.
import type { Cfg } from "./config";
import { squash, type Books, type JLine } from "./wehago";

export const CLOSING_KEEP = ["상각비", "퇴직급여", "대손상각", "충당금전입", "법인세"];

/** 그대로 쓸 줄, 결산 비용이면 대변을 비운 줄, 뺄 줄이면 null. */
export function closingPlLine(ln: JLine, closingSorts: readonly string[]): JLine | null {
  const sorts = new Set(closingSorts.map((s) => squash(s)));
  if (!sorts.has(squash(ln.sort)) || !/^[4-9]/.test(squash(ln.account_code))) return ln;
  if (CLOSING_KEEP.some((w) => squash(ln.account).includes(w)) && ln.debit) return { ...ln, credit: null };
  return null;
}

/** drop_closing_pl -> 뺀 줄 수 */
export function dropClosingPl(books: Books, cfg: Cfg): number {
  const keep: JLine[] = [];
  let dropped = 0;
  for (const ln of books.journal) {
    const v = closingPlLine(ln, cfg.closing_sorts);
    if (v === null) dropped++;
    else keep.push(v);
  }
  books.journal = keep;
  if (dropped) books.notes.push(`결산 전표 손익 줄 ${dropped}건 뺌 (원가 대체·손익 대체, 감가상각비 차변은 남김)`);
  return dropped;
}
