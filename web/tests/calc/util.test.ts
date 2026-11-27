import { describe, expect, it } from "vitest";
import { cmpStr, fmtComma, floorDiv, pyFixed, pyG, pyIsDigit, pyMod, pyRound, pyStrip, sortedBy } from "../../src/model/py";
import { Issues, isBlank, man, maskRrn, num, parseDate, pct, settingNum, ssum, ssumOrNone, won, type Row } from "../../src/model/util";
import { normCode, normVendor } from "../../src/model/vendor";
import { dictReader, parseCsv, readCsv, writeCsv } from "../../src/model/csv";

// 기대값은 파이썬 ceo_report/util.py 로 얻은 것
describe("py", () => {
  it("pyRound 은 은행가 반올림", () => {
    expect([2.5, 3.5, -2.5, 0.5, -0.5, 1.5, 2.4999, -1.6].map(pyRound)).toEqual([2, 4, -2, 0, 0, 2, 2, -2]);
  });
  it("정수 나눗셈·나머지", () => {
    expect(floorDiv(-7, 2)).toBe(-4);
    expect(pyMod(-1, 7)).toBe(6);
    expect(pyMod(-3, 7)).toBe(4);
  });
  it("포맷", () => {
    expect(fmtComma(1234567)).toBe("1,234,567");
    expect(fmtComma(-1000)).toBe("-1,000");
    expect(fmtComma(0)).toBe("0");
    expect(pyFixed(0.25, 1)).toBe("0.2");
    expect(pyFixed(0.35, 1)).toBe("0.3");   // 0.35 는 실제로 0.34999…
    expect(pyFixed(0.75, 1)).toBe("0.8");
    expect(pyFixed(123456.789, 1, true)).toBe("123,456.8");
    expect(pyG(0.7)).toBe("0.7");
    expect(pyG(100)).toBe("100");
    expect(pyG(1e-5)).toBe("1e-05");
    expect(pyG(1234567)).toBe("1.23457e+06");
  });
  it("공백·숫자 판정", () => {
    expect(pyStrip("\x1c a \x85")).toBe("a");
    expect(pyStrip("﻿a")).toBe("﻿a");
    expect(pyIsDigit("00123")).toBe(true);
    expect(pyIsDigit("²")).toBe(true);
    expect(pyIsDigit("１２")).toBe(true);
    expect(pyIsDigit("1a")).toBe(false);
    expect(pyIsDigit("")).toBe(false);
  });
  it("글자 비교·안정 정렬", () => {
    expect(cmpStr("\u{1F600}", "￿")).toBe(1);
    expect(sortedBy([[1, "b"], [0, "a"], [1, "a"]], (x) => x[0] as number).map((x) => x[1])).toEqual(["a", "b", "a"]);
  });
});

describe("util", () => {
  it("won·man·pct", () => {
    expect([0, 5, -5, 1234567, -1234567.9, 1e15, null, 2.5].map((x) => won(x))).toEqual(
      ["0", "5", "−5", "1,234,567", "−1,234,567", "1,000,000,000,000,000", "미확인", "2"]);
    expect([0, 1250000, -1350000, 250000, 150000, null, 123456789012].map((x) => man(x))).toEqual(
      ["0.0", "1.2", "−1.4", "0.2", "0.1", "미확인", "123,456.8"]);
    expect([[1, 8], [1, 3], [5, 0], [null, 3], [1, 16]].map(([a, b]) => pct(a ?? null, b ?? null))).toEqual(
      ["12.5%", "33.3%", "판단 불가", "판단 불가", "6.2%"]);
  });
  it("num", () => {
    const N = ["1,234,000", "-500", "(500)", "2.5", "3.5", "-2.5", "", "-", "미확인", "abc", "１２３", "12원", " 7 ", "+4", "1.", "0.5"];
    expect(N.map((x) => num(x))).toEqual([1234000, -500, -500, 2, 4, -2, null, null, null, null, 123, 12, 7, 4, null, 0]);
    expect(isBlank(null)).toBe(true);
    const iss = new Issues();
    const row: Row = { _file: "a.csv", _line: 3, 금액: "x" };
    expect(num("x", iss, row, "금액")).toBeNull();
    expect(iss.items).toEqual([["a.csv", 3, "금액 값이 숫자가 아님: 'x' (미확인으로 처리)"]]);
  });
  it("parseDate", () => {
    const D = ["2026-11-02", "2026.11.2", "2026/11/02.", "20261102", "2026-13-01", "26-11-02", "2026-11-02 09:00", " ", "x"];
    expect(D.map((x) => parseDate(x))).toEqual(
      ["2026-11-02", "2026-11-02", "2026-11-02", "2026-11-02", null, null, "2026-11-02", null, null]);
    const iss = new Issues();
    parseDate("2026-13-01", iss, { _file: "b.csv", _line: 2 }, "일자");
    expect(iss.items).toEqual([["b.csv", 2, "일자 날짜 형식 오류: '2026-13-01' (날짜 없음으로 처리)"]]);
  });
  it("settingNum·ssum", () => {
    expect(["50,000,000", "100%", "0.70", "", "abc", "1.0"].map((v) => settingNum({ a: v }, "a", 7))).toEqual(
      [[50000000, null], [100, null], [0.7, null], [7, "설정 비어 있음"], [7, "숫자 아님"], [1, null]]);
    expect(settingNum({}, "a", 7)).toEqual([7, "설정 비어 있음"]);
    expect(ssum([1, null, 2])).toEqual([3, 1]);
    expect(ssumOrNone([null, null])).toEqual([null, 2]);
    expect(ssumOrNone([])).toEqual([0, 0]);
  });
  it("maskRrn", () => {
    expect(maskRrn("주민 900101-1234567 끝")).toBe("주민 ******-******* 끝");
    expect(maskRrn(null)).toBe("");
  });
});

describe("vendor", () => {
  it("normVendor·normCode", () => {
    expect(normVendor("㈜ 무대 제작사")).toBe("무대제작사");
    expect(normVendor("주식회사 가나")).toBe("가나");
    expect(normVendor(null)).toBe("");
    expect(normCode("000101")).toBe("101");
    expect(normCode("000")).toBe("0");
    expect(normCode(" 0 01 ")).toBe("1");
    expect(normCode("A01")).toBe("A01");
    expect(normCode(null)).toBe("");
  });
});

describe("csv", () => {
  it("파이썬 csv.reader 와 같은 줄 번호", () => {
    const t = 'a,b\r\n"x\ny",2\r\n\r\n"q""r"s,3\n';
    expect(parseCsv(t)).toEqual([
      { cells: ["a", "b"], lineNum: 1 }, { cells: ["x\ny", "2"], lineNum: 3 }, { cells: [], lineNum: 4 },
      { cells: ['q"rs', "3"], lineNum: 5 }]);
    expect(parseCsv('a,"b')).toEqual([{ cells: ["a", "b"], lineNum: 1 }]);
  });
  it("readCsv: 제목 줄·빈 줄·짧은 줄·같은 머리글", () => {
    const iss = new Issues();
    const info: { missing?: string[]; header?: string[] } = {};
    const [rows, ok] = readCsv("t.csv", "제목\r\n\r\n 이름 ,금액,비고,비고\r\n가, 1 \r\n,,,\r\n나\r\n", ["이름", "금액"], iss, info);
    expect(ok).toBe(true);
    expect(rows).toEqual([
      { 이름: "가", 금액: "1", 비고: "", _line: 4, _file: "t.csv" },
      { 이름: "나", 금액: "", 비고: "", _line: 6, _file: "t.csv" }]);
    expect(iss.items).toEqual([
      ["t.csv", 3, "머리글 위 제목 줄 1줄을 건너뛰고 3번째 줄을 머리글로 읽음"],
      ["t.csv", 1, "머리글이 두 번 있음: 비고 — 앞 칸 값을 씀"]]);
    expect(info.missing).toEqual([]);
    const iss2 = new Issues();
    expect(readCsv("x.csv", undefined, ["a"], iss2)).toEqual([[], false]);
    expect(iss2.items).toEqual([["x.csv", "-", "파일 없음 (이 묶음은 '자료 없음'으로 표시)"]]);
  });
  it("dictReader·writeCsv", () => {
    expect(dictReader("a,b,a\r\n1,2,3\r\n\r\n4\r\n")).toEqual([{ a: "3", b: "2" }, { a: null, b: null }]);
    expect(writeCsv([["a", "b,c", 'd"e', "f\ng"], [""], []])).toBe('a,"b,c","d""e","f\ng"\r\n""\r\n\r\n');
  });
});
