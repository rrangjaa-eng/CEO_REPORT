import {beforeEach, describe, expect, it} from "vitest";
import {installFakeChrome} from "./fakeChrome";
import {SITE_ORIGIN} from "../src/config";
import {storeDoc} from "../src/docs";
import {handleExternal, registerExternal} from "../src/external";

const fromSite = {origin: SITE_ORIGIN, url: SITE_ORIGIN + "/"} as chrome.runtime.MessageSender;

describe("onMessageExternal", () => {
  let fake: ReturnType<typeof installFakeChrome>;
  beforeEach(() => { fake = installFakeChrome("1.0.0"); });

  it("다른 사이트는 거절한다", async () => {
    await storeDoc("a.json", "2026-11-27 09:00:00", {"종류": "분개장"});
    for (const origin of ["https://evil.example.com", "https://ceo-report-627830629386.us-central1.run.app.evil.com", "http://ceo-report-627830629386.us-central1.run.app", undefined]) {
      const r = await handleExternal({type: "list"}, {origin} as chrome.runtime.MessageSender);
      expect(r).toEqual({ok: false, error: "허용되지 않은 사이트"});
    }
  });

  it("ping 은 버전을 준다", async () => {
    expect(await handleExternal({type: "ping"}, fromSite)).toEqual({ok: true, version: "1.0.0"});
  });

  it("list 는 보관한 문서를 준다", async () => {
    const doc = {"종류": "분개장", "기간": {start_date: "20260101"}, "회사": "가", "줄수": 0, "열": [], "줄": []};
    await storeDoc("261127 분개장 자동수집.json", "2026-11-27 09:00:00", doc);
    const r = await handleExternal({type: "list"}, fromSite);
    expect(r).toEqual({ok: true, version: "1.0.0", docs: [{name: "261127 분개장 자동수집.json", savedAt: "2026-11-27 09:00:00", doc}]});
  });

  it("list 는 아무것도 없으면 빈 목록", async () => {
    expect(await handleExternal({type: "list"}, fromSite)).toEqual({ok: true, version: "1.0.0", docs: []});
  });

  it("등록한 듣개가 비동기로 답한다 (true 를 돌려 통로를 열어 둠)", async () => {
    registerExternal();
    expect(fake.external).toHaveLength(1);
    const bad = await new Promise((res) => { expect(fake.external[0]!({type: "list"}, {origin: "https://x.example"}, res)).toBe(true); });
    expect(bad).toEqual({ok: false, error: "허용되지 않은 사이트"});
    const ok = await new Promise((res) => { fake.external[0]!({type: "ping"}, fromSite, res); });
    expect(ok).toEqual({ok: true, version: "1.0.0"});
  });
});
