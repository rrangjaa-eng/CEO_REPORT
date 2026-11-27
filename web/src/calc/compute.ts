// calc.compute 의 타입스크립트 판. 절 순서는 파이썬 원본과 같다(1 → 3 → 5 → 2 → 4 → 6 → 7 → 꼬리).
import type { Data } from "../model/data";
import type { IsoDate } from "../model/dates";
import type { Ctx, Kind, Obj } from "./ctx";
import { head } from "./head";
import { section1 } from "./s1";
import { section3 } from "./s3";
import { section5 } from "./s5";
import { section2 } from "./s2";
import { section4 } from "./s4";
import { section6 } from "./s6";
import { section7 } from "./s7";
import { tail } from "./tail";

export function compute(d: Data, kind: Kind, asof: IsoDate, start: IsoDate | null = null,
                        pick: unknown = null, payday: IsoDate | null = null): Obj {
  const ctx = head(d, kind, asof, start, pick, payday); // calc.py 145-200: issues·R·payday·period·settings
  section1(ctx); // 201-287
  section3(ctx); // 288-463
  section5(ctx); // 464-537
  section2(ctx); // 538-756 (일정·자금계획·세금·부채·s2)
  section4(ctx); // 757-783
  section6(ctx); // 784-841
  section7(ctx); // 842-886
  tail(ctx);     // 887-905 (targets·budget·dep·acct_year·last_pay·plan_gap_note·risks)
  return ctx.R;
}

export type { Ctx };
