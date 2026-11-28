// 과대·과소 점검(2026-11-27)에서 찾은 것 중 숫자가 바뀌는 고침. 사용자가 2026-11-28 에 셋 다 켜기로 결정 (RULES 기본값 true).
// '꺼짐' 시험은 스위치를 끄고 옛 프로그램의 숫자를 보여 준다.
import { afterEach, describe, expect, it } from "vitest";
import { compute } from "../../src/calc/compute";
import { mergeTax } from "../../src/calc/tax";
import { RULES } from "../../src/model/rules";
import { loadData } from "../../src/model/data";
import { loadCase } from "./golden";

const rep = (f: Record<string, string>, name: string, a: string, b: string) => {
  if (!f[name]!.includes(a)) throw new Error(`${name} 에 '${a}' 없음`);
  f[name] = f[name]!.replace(a, b);
};
const run = (id: string, mut: (f: Record<string, string>) => void = () => {}) => {
  const c = loadCase(id);
  mut(c.files);
  return compute(loadData(c.files), "weekly", c.case.asof);
};
const outAll = (R: Record<string, any>) => R["s2"].buckets.reduce((t: number, b: any) => t + b.out_firm + b.out_est, 0);
const saved = { ...RULES };
afterEach(() => Object.assign(RULES, saved));

describe("기본값은 모두 켜짐 (사용자 결정 2026-11-28)", () => {
  it("RULES 의 모든 값이 true", () => expect(Object.values(RULES).every((v) => v === true)).toBe(true));
});

describe("overdueOutNextFriday: 예정일 지난 자금일정 지급", () => {
  const late = (f: Record<string, string>) => rep(f, "자금일정.csv", '2026-11-10,지급,"3,300,000"', '2026-10-30,지급,"3,300,000"');

  it("꺼짐: 예상 지출에서 빠지고 past 에만 남는다 (옛 프로그램)", () => {
    RULES.overdueOutNextFriday = false;
    const R = run("base", late);
    expect(outAll(R)).toBe(outAll(run("base")) - 3300000);
    expect(R["s2"].past_out).toBe(3300000);
  });

  it("켜짐: 다음 금요일의 예상(확정 아님) 지출로 옮긴다", () => {
    RULES.overdueOutNextFriday = true;
    const R = run("base", late);
    expect(outAll(R)).toBe(outAll(run("base")));
    expect(R["s2"].past_out).toBe(0);
    expect(R["late_out"].map((e: any) => [e.orig_date, e.date, e.amount, e.firm, e.must])).toEqual([["2026-10-30", "2026-11-06", 3300000, false, false]]);
    // 확정 잔액은 그대로, 예상 포함 잔액만 줄어든다
    expect(R["s2"].buckets[0].out_est).toBe(run("base")["s2"].buckets[0].out_est + 3300000);
    expect(R["s2"].buckets[0].bal_firm).toBe(run("base", late)["s2"].buckets[0].bal_firm);
    // 대조 줄(일정 합계 = 기간별 + …)이 여전히 맞는다
    const chk = (R["s7"].checks as any[]).find((c) => String(c[0]).startsWith("예정 일정 합계"));
    expect(chk[3]).toBe(true);
  });

  it("켜짐: 가장 낮은 잔액(min)과 기간별 가용자금에도 들어간다", () => {
    RULES.overdueOutNextFriday = true;
    const a = run("base", late), b = run("base");
    expect(a["s2"].min.all[0]).toBe(b["s2"].min.all[0]);
    // 첫 기간(출금일 11-06 까지)에 옮긴 330만이 더해진다 (원래 예정일 11-10 은 첫 기간 밖이었음)
    expect(a["s2"].periods[0].all.out).toBe(b["s2"].periods[0].all.out + 3300000);
    expect(a["s2"].periods[0].firm.out).toBe(b["s2"].periods[0].firm.out);
  });
});

describe("overdueOutNextFriday: 이미 낸 것과 오래된 것은 옮기지 않는다 (검토 반영)", () => {
  it("통장에 같은 금액 출금이 예정일 3일 전부터 있으면 이미 낸 것으로 보고 옮기지 않는다", () => {
    RULES.overdueOutNextFriday = true;
    const R = run("base", (f) => { f["자금일정.csv"] += '2026-10-28,지급,"8,000,000",확정,임차료,,건물관리,계약,\n'; });
    expect(R["late_out"]).toEqual([]);
    expect(outAll(R)).toBe(outAll(run("base")));
    expect(R["s2"].past_out).toBe(8000000);
  });

  it("급여·4대보험·세금·카드대금처럼 제 날짜에 저절로 나가는 정기 지출은 옮기지 않는다 (금액이 통장과 달라도 나간 것으로 봄)", () => {
    RULES.overdueOutNextFriday = true;
    const R = run("base", (f) => { f["자금일정.csv"] += '2026-10-25,지급,"45,000,000",확정,급여,,직원,급여대장,\n'; });
    expect(R["late_out"]).toEqual([]);
    expect(R["s2"].past_out).toBe(45000000);
  });

  it("예정일이 31일 넘게 지난 줄은 옮기지 않는다 (정리 안 된 옛 일정)", () => {
    RULES.overdueOutNextFriday = true;
    const R = run("base", (f) => { f["자금일정.csv"] += '2026-09-30,지급,"1,234,000",확정,거래처미지급,,옛거래처,청구서,\n'; });
    expect(R["late_out"]).toEqual([]);
    expect(R["s2"].past_out).toBe(1234000);
  });
});

describe("taxSameMonth: 세금 일정이 납부일과 같은 달이면 같은 세금", () => {
  // 기본 사례: 세금예상 부가세 4분기 납부 2027-01-25, 자금일정에 세무서 부가세 35,000,000 (2027-01-25)
  const mut = (f: Record<string, string>) => {
    rep(f, "세금예상.csv", "-15440000", "15440000");
    rep(f, "자금일정.csv", "2027-01-25,지급,\"35,000,000\"", "2027-01-12,지급,\"35,000,000\"");
  };
  const near = (f: Record<string, string>) => rep(f, "세금예상.csv", "-15440000", "15440000");

  it("꺼짐: 13일 떨어지면 일정 3,500만과 세금 예상 1,544만이 둘 다 나간다 (옛 프로그램)", () => {
    RULES.taxSameMonth = false;
    expect(outAll(run("base", mut))).toBe(outAll(run("base", near)) + 15440000);
  });

  it("켜짐: 같은 달이면 하나로 본다", () => {
    RULES.taxSameMonth = true;
    const R = run("base", mut);
    expect(outAll(R)).toBe(outAll(run("base", near)));
    const t = R["tax"].find((x: any) => x.kind === "부가세" && x.due === "2027-01-25");
    expect([t.matched.date, t.matched.amount, t.diff]).toEqual(["2027-01-12", 35000000, 19560000]);
  });

  it("켜짐: 다른 달 일정과는 맞추지 않는다", () => {
    RULES.taxSameMonth = true;
    const far = (f: Record<string, string>) => {
      near(f);
      rep(f, "자금일정.csv", "2027-01-25,지급,\"35,000,000\"", "2026-12-28,지급,\"35,000,000\"");
    };
    expect(outAll(run("base", far))).toBe(outAll(run("base", near)) + 15440000);
  });
});

describe("taxSameMonth: 같은 달 다른 세금과 섞지 않는다 (검토 반영)", () => {
  const tx = (kind: string, due: string, amount: number, codes: string[] = []) =>
    ({ kind, period: "", due, amount, state: "예상", basis: "", codes, book: null });
  const ev = (date: string, amount: number, cat: string, desc: string, vendor_code = "") =>
    ({ date, io: "out", amount, firm: true, cat, desc, basis: "", project: "", source: "자금일정", vendor_code });
  const total = (evs: { amount: number | null }[]) => evs.reduce((t, e) => t + (e.amount ?? 0), 0);

  it("거래처코드가 같은 세무서여도 원천세가 같은 달 부가세 일정을 가져가지 않는다", () => {
    RULES.taxSameMonth = true;
    const events = [ev("2027-01-11", 3100000, "세금", "세무서 원천세", "900"), ev("2027-01-25", 35000000, "세금", "세무서 부가세", "900")];
    const [out, info] = mergeTax(events, [tx("원천세", "2027-01-11", 3100000, ["900"]), tx("부가세", "2027-01-25", 35000000, ["900"])], "2026-11-02");
    expect(total(out)).toBe(38100000);
    expect(info.map((t) => t.diff)).toEqual([0, 0]);
  });

  it("다른 세금의 납부일 가까이에 있는 일정은 같은 달이라는 이유로 가져가지 않는다", () => {
    RULES.taxSameMonth = true;
    const events = [ev("2027-04-30", 4000000, "세금", "구청 법인지방소득세 신고"), ev("2027-04-12", 3100000, "세금", "세무서 원천세")];
    const [out] = mergeTax(events, [tx("원천세", "2027-04-12", 3100000), tx("법인지방소득세", "2027-04-30", 4000000)], "2026-11-02");
    expect(total(out)).toBe(7100000);
  });
});

describe("bookKeepsManualDeposit: 장부 잔액을 쓸 때 손으로 넣은 정기예금", () => {
  const dep = (f: Record<string, string>) => {
    f["계좌잔액.csv"] += '2026-11-02,정기예금,가상은행,"90,000,000","90,000,000",정기예금 만기 2027-04-15\n';
  };

  it("꺼짐: 원금은 0 이 되고 제한만 빠져 쓸 수 있는 돈이 9,000만 작게 나온다 (옛 프로그램)", () => {
    RULES.bookKeepsManualDeposit = false;
    const a = run("u_book_balance"), b = run("u_book_balance", dep);
    expect(b["s1"].total).toBe(a["s1"].total);
    expect(b["s1"].available).toBe(a["s1"].available - 90000000);
  });

  it("켜짐: 정기예금 원금은 살리고 제한으로 빼서 쓸 수 있는 돈이 그대로다", () => {
    const a = run("u_book_balance");
    RULES.bookKeepsManualDeposit = true;
    const b = run("u_book_balance", dep);
    expect(b["s1"].total).toBe(a["s1"].total + 90000000);
    expect(b["s1"].available).toBe(a["s1"].available);
  });
});
