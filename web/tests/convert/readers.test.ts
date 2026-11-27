// 엑셀 읽기 바닥 부품: .xls(BIFF8) · zip · xml. .xls 는 golden 사례에 없으므로 tests/xls_fixture.py 로 만든 합성 파일과
// 파이썬 read_xls · read_journal_xls 결과(fixtures/xls_expected.json)를 맞춘다.
import { describe, expect, it } from "vitest";
import { readXls } from "../../src/convert/xls";
import { readJournalXls } from "../../src/convert/wehago";
import { openZip, ZipError } from "../../src/convert/zip";
import { parseXml, xmlText } from "../../src/convert/xml";
import { readFixture } from "./cases";

type Exp = Record<string, { cells?: (string | number)[][]; error?: string; rows?: string[][]; period?: [string, string] | null; company?: string | null }>;
const expected = JSON.parse(new TextDecoder().decode(readFixture("xls_expected.json"))) as Exp;

describe(".xls 읽기 (파이썬 read_xls 와 같음)", () => {
  for (const name of ["small.xls", "large.xls", "split.xls", "biff5.xls", "notxls.xls"]) {
    it(name, () => {
      const want = expected[name]!;
      if (want.error !== undefined) expect(() => readXls(readFixture(name))).toThrow(want.error);
      else expect(readXls(readFixture(name))).toEqual(want.cells);
    });
  }
  it("분개장 인쇄 저장 파일 (read_journal_xls)", () => {
    const want = expected["분개장_2026.xls"]!;
    const got = readJournalXls(readFixture("분개장_2026.xls"), "분개장_2026.xls");
    expect(got.rows).toEqual(want.rows);
    expect(got.period ?? null).toEqual(want.period);
    expect(got.company ?? null).toEqual(want.company);
  });
});

describe("zip", () => {
  const z = openZip(readFixture("small.zip"));
  it("부품 이름", () => expect(z.names).toEqual(["stored.txt", "deflated.xml"]));
  it("저장(stored) 부품", async () => expect(new TextDecoder().decode(await z.read("stored.txt", 1000))).toBe("가나다 stored"));
  it("압축(deflate) 부품과 크기 제한", async () => {
    const n = z.size("deflated.xml")!;
    expect((await z.read("deflated.xml", n)).length).toBe(n);
    await expect(z.read("deflated.xml", n - 1)).rejects.toThrow(ZipError);
    await expect(z.read("없는부품", 10)).rejects.toThrow(ZipError);
  });
  it("zip 이 아니면 ZipError", () => expect(() => openZip(new Uint8Array(100))).toThrow(ZipError));
});

describe("xml", () => {
  it("글자 참조·속성", async () => {
    const z = openZip(readFixture("small.zip"));
    const el = parseXml(xmlText(await z.read("deflated.xml", 1 << 20)));
    expect(el.tag).toBe("a");
    expect(el.attrs["x"]).toBe("1");
    expect(el.text.endsWith("&<가")).toBe(true);
  });
});
