import { describe, expect, it } from "vitest";
import { buildConvInput, collectedMs, docFileName, nameOf, seoulDate, seoulNow } from "../../src/collect/inputs";
import type { CollectedDoc } from "../../src/collect/docs";

const journal = (stamp: string, start = "20260101", end = "20261031"): CollectedDoc =>
  ({ 종류: "분개장", 형식: 1, 수집시각: stamp, 회사: "가", 기간: { start_date: start, end_date: end }, 줄수: 0, 열: [], 줄: [] });

describe("서울 시각", () => {
  it("이 PC 시간대와 상관없이 UTC+9", () => {
    expect(seoulDate(Date.UTC(2026, 10, 1, 15, 0, 0))).toBe("2026-11-02");   // UTC 15시 = 서울 다음 날 0시
    expect(seoulDate(Date.UTC(2026, 10, 1, 14, 59, 59))).toBe("2026-11-01");
    expect(seoulNow(Date.UTC(2026, 10, 1, 15, 4, 5))).toBe("2026-11-02 00:04:05");
    expect(collectedMs("2026-11-02 00:04:05")).toBe(Date.UTC(2026, 10, 1, 15, 4, 5));
    expect(collectedMs("모름")).toBeNull();
  });
});

describe("확장 자료의 파일 이름", () => {
  it("확장과 같은 꼴: 'YYMMDD 종류[기간 꼬리] 자동수집.json' (YYMMDD = 수집시각)", () => {
    expect(docFileName(journal("2026-11-05 10:00:00"))).toBe("261105 분개장 자동수집.json");
    expect(docFileName(journal("2026-11-05 10:00:00", "20250101", "20251231"))).toBe("261105 분개장_2025 자동수집.json");
    expect(docFileName(journal("2026-11-05 10:00:00", "20260301", "20261031"))).toBe("261105 분개장_기간20260301-20261031 자동수집.json");
    expect(docFileName({ 종류: "자금계획", 수집시각: "2026-11-01 09:00:00", 기간: { from: "20261001" } })).toBe("261101 자금계획 자동수집.json");
    expect(docFileName({ 종류: "결산원본", 수집시각: "2026-11-01 09:00:00", 화면: "재무상태표", 화면코드: "X1", 연도: 2026 }))
      .toBe("261101 결산_재무상태표_2026 자동수집.json");
    expect(docFileName({ 종류: "자금계획" })).toBe("000000 자금계획 자동수집.json");
  });

  it("확장이 준 이름이 있으면 그것 (경로 조각은 뗌)", () => {
    expect(nameOf(journal("2026-11-05 10:00:00"), "261031 분개장 자동수집.json")).toBe("261031 분개장 자동수집.json");
    expect(nameOf(journal("2026-11-05 10:00:00"), "../../입력/설정.json")).toBe("설정.json");
    expect(nameOf(journal("2026-11-05 10:00:00"), "")).toBe("261105 분개장 자동수집.json");
  });
});

describe("폴더 + 확장 자료 합치기", () => {
  const P = "수집/위하고/261031 분개장 자동수집.json";
  const bytes = (s: string) => new TextEncoder().encode(s);

  it("같은 경로면 더 새것: 확장 자료가 더 늦게 받은 것이면 확장", () => {
    const doc = journal("2026-11-05 10:00:00");
    const r = buildConvInput([{ path: P, lastModified: Date.UTC(2026, 10, 1), bytes: bytes("폴더") }], [{ doc, name: "261031 분개장 자동수집.json" }]);
    expect(r.from[P]).toBe("확장");
    expect(JSON.parse(new TextDecoder().decode(r.files[P]))).toEqual(doc);
    expect(r.mtimes[P]).toBe(collectedMs("2026-11-05 10:00:00")! / 1000);
  });

  it("폴더 파일이 더 늦게 고친 것이면 폴더", () => {
    const r = buildConvInput([{ path: P, lastModified: Date.UTC(2026, 10, 6), bytes: bytes("폴더") }],
      [{ doc: journal("2026-11-05 10:00:00"), name: "261031 분개장 자동수집.json" }]);
    expect(r.from[P]).toBe("폴더");
    expect(new TextDecoder().decode(r.files[P])).toBe("폴더");
  });

  it("이름 없는 예전 자료는 지은 이름으로 들어가고, 입력 파일은 작성일(서울)을 남긴다", () => {
    const r = buildConvInput([{ path: "입력/계산서.csv", lastModified: Date.UTC(2026, 10, 1, 16), bytes: bytes("a") }],
      [{ doc: journal("2026-11-05 10:00:00") }]);
    expect(Object.keys(r.files).sort()).toEqual(["수집/위하고/261105 분개장 자동수집.json", "입력/계산서.csv"]);
    expect(r.fileDays).toEqual({ "입력/계산서.csv": "2026-11-02" });
  });
});
