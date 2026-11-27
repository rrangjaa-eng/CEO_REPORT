// calc.compute 한 함수를 절 파일로 나눌 때, 절 사이에 넘기는 지역 변수(파이썬 이름 그대로).
// 절 함수는 ctx 를 읽고 ctx.R 과 아래 칸을 채운다. 파이썬 원본: ceo_report/calc.py compute (145-905).
import type { Data } from "../model/data";
import type { Issues } from "../model/util";
import type { IsoDate } from "../model/dates";

export type Kind = "weekly" | "monthly";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Obj = Record<string, any>;

export interface Ctx {
  d: Data;
  kind: Kind;
  asof: IsoDate;
  start: IsoDate | null;
  pick: unknown;
  payday: IsoDate | null;
  R: Obj;
  issues: Issues;
  /** 대조표: [항목, 값A, 값B, 일치여부] */
  checks: [string, unknown, unknown, boolean][];
  // 머리(A0)
  p0: IsoDate;
  p1: IsoDate;
  in_missing: string[];
  invs: Obj[];
  // s1
  in_p: Obj[];
  stale_accounts: Obj[];
  // s3
  proj: Map<string, Obj>; // 파이썬 OrderedDict: 넣은 순서 유지
  plist: Obj[];
  // s5
  ar_rows: Obj[];
  inv_proj: unknown;
  // s2
  events: Obj[];
  // s4
  ym: string;
  year: string;
  pl_out: Map<string, Obj>;
  /** 파이썬 루프 변수가 함수 끝까지 남아 뒤 절에서 쓰이는 경우(P 등)는 여기에 이름 그대로 둔다. */
  leaked: Obj;
}
