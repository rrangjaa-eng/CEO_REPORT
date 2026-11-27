import { describe, expect, it } from "vitest";
import { diffPaths, loadCase } from "./golden";
import { loadData } from "../../src/model/data";

type Obj = Record<string, unknown>;
const plain = (x: unknown) => JSON.parse(JSON.stringify(x)) as unknown;

const CASES = ["base", "u_unknown_not_zero", "u_no_fundplan", "u_book_balance", "d_deposit_manual", "d_deposit_book", "f_tax_merge"];

describe("loadData: golden weekly 기대값의 s1 원본 줄과 같음", () => {
  for (const id of CASES) {
    it(id, () => {
      const g = loadCase(id);
      const d = loadData(g.files);
      const s1 = (g.expected.weekly?.R as Obj | null)?.["s1"] as Obj;
      const accounts = s1["accounts"] as Obj[];
      const txns = s1["txns"] as Obj[];
      expect(accounts.length).toBeGreaterThan(0);
      // compute 가 balance 등을 다시 쓰므로 (낡은 잔액 → null 등) 원본 줄(row)만 비교한다
      for (const a of accounts) {
        const hit = d.balances.find((b) => diffPaths(a["row"], plain(b.row), 1).length === 0);
        expect(hit, JSON.stringify(a["row"])).toBeDefined();
      }
      for (const t of txns) {
        const hit = d.txns.find((x) => diffPaths(t["row"], plain(x.row), 1).length === 0);
        expect(hit, JSON.stringify(t["row"])).toBeDefined();
        for (const k of ["date", "amount", "io", "account", "cat", "vendor", "memo", "project"]) {
          expect((hit as unknown as Obj)[k], k).toEqual(t[k]);
        }
      }
    });
  }

  it("u_unknown_not_zero: 잔액 빈칸은 0 이 아니라 null", () => {
    const d = loadData(loadCase("u_unknown_not_zero").files);
    expect(d.balances.some((b) => b.balance === null)).toBe(true);
    expect(d.balances.every((b) => b.balance !== 0 || b.row["잔액"] === "0" || b.row["잔액"] === "")).toBe(true);
  });

  it("u_no_fundplan: 자금계획 없음 → fundplan null, issues 는 파이썬 data.load 와 같음", () => {
    const d = loadData(loadCase("u_no_fundplan").files);
    expect(d.fundplan).toBeNull();
    expect(d.fundplan_problem).toBe("");
    expect(d.fundplan_received).toEqual([]);
    // python3 -c "from ceo_report import data; data.load(<변환 뒤 입력 폴더>).issues.items"
    expect(d.issues.items).toEqual([
      ["장부알림.csv", "-", "분개장이 2026-09-15부터라 작년 분개장이 빠졌음 (전기이월·설립 자본금 줄 없음) — 수집\\위하고 에 작년 분개장(예: 분개장_2025.xls)을 함께 넣으세요. 그 전까지 통장 잔액은 분개장으로 만들지 않고, 미지급금·차입금·매출채권은 올해 늘고 준 금액만입니다"],
      ["프로젝트집행.csv", 12, "프로젝트번호 '26999'가 프로젝트.csv에 없음 (프로젝트 미연결로 집계)"],
      ["프로젝트집행.csv", 16, "프로젝트번호 '26299'가 프로젝트.csv에 없음 (프로젝트 미연결로 집계)"],
      ["프로젝트집행.csv", "-", "프로젝트번호 빈칸 줄 1건 → 프로젝트 미연결로 집계 (어느 줄인지는 변환결과.txt [연결])"],
    ]);
  });

  it("파일이 없으면 파이썬과 같은 알림·out_missing·in_missing", () => {
    const d = loadData({});
    expect(d.out_missing).toEqual(["자금일정.csv (파일 없음)", "프로젝트집행.csv (파일 없음)"]);
    expect(d.in_missing).toEqual(["계산서.csv (파일 없음)"]);
    expect(d.issues.items[0]).toEqual(["설정.csv", "-", "파일 없음 (이 묶음은 '자료 없음'으로 표시)"]);
    expect(d.issues.items).toHaveLength(12);
    expect(d.settings["예산_원가율"]).toBe("0.70");
    expect(d.debts).toBeNull();
    expect(d.tax).toBeNull();
  });

  it("열이 빠지면 필수 열 없음", () => {
    const d = loadData({ "자금일정.csv": "예정일,입출금\r\n2026-11-06,출금\r\n", "자금계획.csv": "예정일\r\n" });
    expect(d.out_missing[0]).toBe("자금일정.csv (필수 열 없음: 금액)");
    expect(d.fundplan).toBeNull();
    expect(d.fundplan_problem).toBe("필수 열 없음: 입출금, 거래처, 금액, 대상월, 자료일, 상태");
  });
});
