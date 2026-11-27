// 0.9.6(chrome_extension/)과 같은 화면·NEED 값을 쓰는지 맞춰 본다 (옛 확장은 교체 때까지 그대로 쓰므로 두 쪽이 어긋나면 안 됨)
import {describe, expect, it} from "vitest";
import oldBg from "../../chrome_extension/background.js?raw";
import oldManifest from "../../chrome_extension/manifest.json";
import manifest from "../manifest.json";
import {AUTO_SCREENS, NEED, RECON_SCREENS, hasData} from "../src/screens";

const objLiteral = (name: string): string => {
  const m = oldBg.match(new RegExp(`const ${name} = (\\[[\\s\\S]*?\\n\\]|\\{[^\\n]*\\});`));
  if (!m) throw new Error(`${name} 를 찾지 못함`);
  return m[1]!;
};
// 옛 JS 객체 글을 값으로 (주석 빼고 Function 으로 읽음 — 시험 안에서 저장소의 우리 파일만 읽는다)
// eslint-disable-next-line @typescript-eslint/no-implied-eval
const evalLit = (src: string): unknown => new Function(`return (${src.replace(/\/\/[^\n]*/g, "")});`)();

describe("0.9.6 과 같은 값", () => {
  it("NEED", () => { expect(NEED).toEqual(evalLit(objLiteral("NEED"))); });
  it("AUTO_SCREENS", () => { expect(AUTO_SCREENS).toEqual(evalLit(objLiteral("AUTO_SCREENS"))); });
  it("RECON_SCREENS", () => { expect(RECON_SCREENS).toEqual(evalLit(objLiteral("RECON_SCREENS"))); });
  it("manifest: key·버전·externally_connectable 말고는 같다", () => {
    const {key: _k, version: _v, externally_connectable: _e, ...rest} = manifest;
    const {version: _ov, ...oldRest} = oldManifest;
    expect(rest).toEqual(oldRest);
  });
});

describe("hasData", () => {
  it("NEED 응답이 와야 받음으로 친다", () => {
    expect(hasData({code: "SACL0105"}, [{path: "/smarta/sacl0105/main/", data: {}}])).toBe(true);
    expect(hasData({code: "SACL0105"}, [{path: "/smarta/sacl0105/init", data: {}}])).toBe(false);
  });
  it("오류 응답은 치지 않는다 (error_str 칸만 있는 정상 응답은 침)", () => {
    expect(hasData({code: "SACL0105"}, [{path: "/smarta/sacl0105/main", data: {status: 500}}])).toBe(false);
    expect(hasData({code: "SACL0105"}, [{path: "/smarta/sacl0105/main", data: {error: "x", status: 200}}])).toBe(false);
    expect(hasData({code: "SACL0105"}, [{path: "/smarta/sacl0105/main", data: {error_str: "x"}}])).toBe(true);
  });
  it("NEED 에 없는 화면은 오류가 아닌 응답 하나면 된다", () => {
    expect(hasData({code: "XXXX0000"}, [{path: "/a", data: []}])).toBe(true);
  });
});
