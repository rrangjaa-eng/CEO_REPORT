// convert.py 의 Table·Check 와 CSV 쓰기 (UTF-8 BOM + csv.writer, 모든 칸 주민번호 가림).
import { writeCsv } from "../model/csv";
import { maskRrn, won } from "../model/util";

export interface Check { label: string; source: number | null; csv: number | null }

export const check = (label: string, source: number | null, csv: number | null): Check => ({ label, source, csv });

export function checkResult(c: Check): string {
  if (c.source === null || c.csv === null) return "판단 불가";
  return c.source === c.csv ? "일치" : "불일치";
}

export type TRow = Record<string, string | number | null | undefined>;

export class Table {
  name: string;
  columns: string[];
  rows: TRow[];
  checks: Check[];
  notes: string[];
  written: boolean;
  reason: string;
  extra: Record<string, unknown>;
  constructor(name: string, columns: readonly string[], rows: TRow[], opts: { checks?: Check[]; notes?: string[]; written?: boolean;
    reason?: string; extra?: Record<string, unknown> } = {}) {
    this.name = name;
    this.columns = [...columns];
    this.rows = rows;
    this.checks = [...(opts.checks ?? [])];
    this.notes = [...(opts.notes ?? [])];
    this.written = opts.written ?? true;
    this.reason = opts.reason ?? "";
    this.extra = opts.extra ?? {};
  }
}

/** cell_amount: 모르면 '' (0 아님), 아니면 쉼표 없는 정수. */
export function cellAmount(v: number | null | undefined): string {
  return v === null || v === undefined ? "" : String(Math.trunc(v) || 0);
}

/** table_bytes 의 글 (BOM 포함). */
export function tableText(t: Table): string {
  const rows: string[][] = [t.columns.map((c) => maskRrn(c))];
  for (const r of t.rows) rows.push(t.columns.map((c) => maskRrn(Object.prototype.hasOwnProperty.call(r, c) ? r[c] : "")));
  return "﻿" + writeCsv(rows);
}

const COUNT_LABEL = /^(프로젝트 수|지급요청 건수|지급요청 금액 미확인|지급요청마다)|건수|(빈칸|줄 수|원가 줄)$/;

/** check_text */
export function checkText(c: Check): string {
  const unit = COUNT_LABEL.test(c.label) ? "건" : "";
  const side = (v: number | null) => won(v) + (v !== null ? unit : "");
  return `${c.label}: 원본 ${side(c.source)} · CSV ${side(c.csv)} → ${checkResult(c)}`;
}
