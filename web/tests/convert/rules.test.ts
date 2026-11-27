// I6·I8·I9 고침 스위치 (src/convert/rules.ts): 꺼짐 = 지금 프로그램과 같음, 켜면 고친 동작.
import { afterEach, describe, expect, it } from "vitest";
import { defaultConfig } from "../../src/convert/config";
import { buildAccounts } from "../../src/convert/pl";
import { CONVERT_RULES } from "../../src/convert/rules";
import { buildBank } from "../../src/convert/tables";
import { Books, dedupLineIds, type JLine } from "../../src/convert/wehago";

const base = { ...CONVERT_RULES };
afterEach(() => Object.assign(CONVERT_RULES, base));

function line(over: Partial<JLine>): JLine {
  return { date: "2026-10-05", no: "1", account_code: "81100", account: "복리후생비(판)", debit: null, credit: null, vendor: "", memo: "",
    sort: "일반전표", vendor_code: "", code: null, vendor_norm: "", ...over };
}

function books(journal: JLine[]): Books {
  const b = new Books();
  b.state = "ok";
  b.book_date = "2026-10-31";
  b.journal = journal;
  return b;
}

describe("기본값", () => {
  it("모든 스위치는 꺼져 있음 (정답 예시와 같은 결과)", () => {
    expect(CONVERT_RULES).toEqual({ cumulativeDropCoveredMonths: false, journalDedupLineId: false, cashUnreadableNote: false });
  });
});

describe("I6 누적 파일에서 줄이 모두 사라진 달", () => {
  // 새 분개장은 9~10월. 이전 계정별비용.csv 에는 9월 줄이 있는데, 새 분개장에서 9월 비용 줄이 모두 사라졌다(다른 계정으로 고침).
  const journal = [line({ date: "2026-09-01", account_code: "10300", account: "보통예금", debit: 1 }),
    line({ date: "2026-10-05", debit: 50000 })];
  const prev = [{ "연월": "2026-09", "구분": "판매비와관리비", "계정코드": "81100", "계정과목": "복리후생비(판)", "금액": "70000" }];
  it("꺼짐: 9월 옛 값이 남음", () => {
    const t = buildAccounts(books(journal), defaultConfig(), prev);
    expect(t.rows.map((r) => r["연월"])).toEqual(["2026-09", "2026-10"]);
  });
  it("켬: 새 분개장 기간(9~10월)의 옛 줄은 버림", () => {
    CONVERT_RULES.cumulativeDropCoveredMonths = true;
    const t = buildAccounts(books(journal), defaultConfig(), prev);
    expect(t.rows.map((r) => r["연월"])).toEqual(["2026-10"]);
  });
});

describe("I8 같은 줄 번호 두 번", () => {
  const j = [line({ line_id: "A1", debit: 100 }), line({ line_id: "A1", debit: 100 }), line({ line_id: "A2", debit: 5 }),
    line({ date: "2025-10-05", line_id: "A1", debit: 7 })];
  it("꺼짐: 그대로", () => {
    const notes: string[] = [];
    expect(dedupLineIds(j, notes)).toBe(j);
    expect(notes).toEqual([]);
  });
  it("켬: 같은 해 같은 줄 번호는 한 번만 (다른 해는 다른 줄), 알림", () => {
    CONVERT_RULES.journalDedupLineId = true;
    const notes: string[] = [];
    const out = dedupLineIds(j, notes);
    expect(out.map((l) => [l.date, l.line_id])).toEqual([["2026-10-05", "A1"], ["2026-10-05", "A2"], ["2025-10-05", "A1"]]);
    expect(notes).toHaveLength(1);
    expect(notes[0]).toMatch(/^\[확인\] 분개장에 같은 줄 번호가 두 번 나온 줄 1건/);
  });
});

describe("I9 읽지 못한 현금 줄", () => {
  const journal = [
    line({ date: "2026-10-01", no: "1", account_code: "10300", account: "보통예금", debit: 1000, memo: "전기이월" }),
    line({ date: null, no: "2", account_code: "10300", account: "보통예금", credit: 300 }),
    line({ date: "2026-10-03", no: "3", account_code: "10300", account: "보통예금" }),
  ];
  it("꺼짐: 알림 없이 날짜 없는 줄은 빠지고 금액 없는 줄은 0", () => {
    const [bal] = buildBank(books(journal), defaultConfig());
    expect(bal!.notes.some((n) => n.includes("읽지 못한"))).toBe(false);
    expect(bal!.rows.at(-1)!["잔액"]).toBe("1000");
  });
  it("켬: 잔액은 같고 알림을 남김", () => {
    CONVERT_RULES.cashUnreadableNote = true;
    const [bal] = buildBank(books(journal), defaultConfig());
    expect(bal!.rows.at(-1)!["잔액"]).toBe("1000");
    expect(bal!.notes).toContain("[확인] 보통예금 줄 중 날짜를 읽지 못한 1줄은 빼고, 금액을 읽지 못한 1줄은 0으로 셈 — 장부잔액이 틀릴 수 있음 (위하고에서 분개장을 다시 받으세요)");
  });
});

describe("적요 만기일", () => {
  it("전각 숫자도 파이썬 int() 처럼 읽고, 못 읽으면 날짜를 만들지 않는다", async () => {
    const { memoDate } = await import("../../src/convert/tables");
    expect(memoDate("만기 2027.０３.３１")).toBe("2027-03-31");
    expect(memoDate("만기 2027.03.31")).toBe("2027-03-31");
  });
});
