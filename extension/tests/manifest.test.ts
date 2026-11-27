import {describe, expect, it} from "vitest";
import manifest from "../manifest.json";
import {SITE_ORIGIN} from "../src/config";

const KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA32oiq+8wcPpwprqGBOmZfQOjrjuKc26rk2bMNnro9k+g9VT4imI0Tznh8dTBABrkEbxkNJWU0qQmaNE1s1jjUxHhke9Gct9QVxQPFY4YtGa+BNQJKX9/leViTouWUeIE1vQ5cxvtOCP4jjxX/bcF2EcwMf8rlUuphUW5P3E9EVGbroxrXO9Mm3uSdyop4EPa6cGC42JwVxhGyeTweUGScxBiSOblyLXkwUyW8QAVXcX1v25irzEqIizEAhwOXKB1yVqfre6FadE6uXeR3Snh7gzU1L1TIVRD/5RYvcjLJmDvl8OycjLN/93qcaSroiEoh2BSSXGH8kH58JUkzN4K2wIDAQAB";

// 공개 키 → 확장 ID (SHA-256 앞 16바이트를 a~p 로)
async function idOf(key: string): Promise<string> {
  const der = Uint8Array.from(atob(key), (c) => c.charCodeAt(0));
  const h = new Uint8Array(await crypto.subtle.digest("SHA-256", der)).slice(0, 16);
  return [...h].map((b) => String.fromCharCode(97 + (b >> 4)) + String.fromCharCode(97 + (b & 15))).join("");
}

describe("manifest.json", () => {
  it("버전 1.0.0, 이름 그대로", () => {
    expect(manifest.manifest_version).toBe(3);
    expect(manifest.version).toBe("1.0.0");
    expect(manifest.name).toBe("대표보고 위하고 수집");
  });
  it("key 가 정해진 공개 키이고 ID 가 dodaoiliemfamcfhmloenbkcepgpjdac", async () => {
    expect(manifest.key).toBe(KEY);
    expect(await idOf(manifest.key)).toBe("dodaoiliemfamcfhmloenbkcepgpjdac");
  });
  it("권한은 0.9.6 과 같다 (더하지 않음)", () => {
    expect([...manifest.permissions].sort()).toEqual(["downloads", "storage", "tabs", "unlimitedStorage"]);
    expect(manifest.host_permissions).toEqual(["https://smarta.wehago.com/*"]);
  });
  it("externally_connectable 은 내 사이트만", () => {
    expect(manifest.externally_connectable).toEqual({matches: ["https://ceo-report-627830629386.us-central1.run.app/*"]});
    expect(manifest.externally_connectable.matches[0]).toBe(SITE_ORIGIN + "/*");
  });
  it("hook 은 MAIN world, bridge 는 격리 world, 둘 다 위하고 SmartA 에만 document_start", () => {
    const [hook, bridge] = manifest.content_scripts;
    expect(hook).toMatchObject({matches: ["https://smarta.wehago.com/*"], js: ["hook.js"], run_at: "document_start", world: "MAIN", all_frames: false});
    expect(bridge).toMatchObject({matches: ["https://smarta.wehago.com/*"], js: ["bridge.js"], run_at: "document_start", all_frames: false});
    expect(bridge).not.toHaveProperty("world");
    expect(manifest.background).toEqual({service_worker: "background.js"});
    expect(manifest.action.default_popup).toBe("popup.html");
  });
});
