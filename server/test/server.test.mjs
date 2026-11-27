import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { generateKeyPairSync, sign } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { handler } from "../server.mjs";
import { verifyIapJwt, IAP_ISSUER } from "../iap.mjs";

const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "k1", alg: "ES256" };
const KEYS = { k1: jwk };
const NOW = 1_800_000_000;
const b64u = (b) => Buffer.from(b).toString("base64url");

function token(claims = {}, kid = "k1", key = privateKey) {
  const h = b64u(JSON.stringify({ alg: "ES256", kid }));
  const c = b64u(JSON.stringify({ iss: IAP_ISSUER, email: "me@example.com", iat: NOW - 10, exp: NOW + 600, ...claims }));
  const s = sign("sha256", Buffer.from(h + "." + c), { key, dsaEncoding: "ieee-p1363" });
  return `${h}.${c}.${b64u(s)}`;
}

function site(allowed = "me@example.com") {
  const root = mkdtempSync(join(tmpdir(), "web-"));
  mkdirSync(join(root, "assets"));
  writeFileSync(join(root, "index.html"), "<p>hi</p>");
  writeFileSync(join(root, "assets", "index-DZ-TLYoT.js"), "x");
  const srv = createServer(handler({ root, allowed, keys: async () => KEYS, now: () => NOW }));
  return new Promise((ok) => srv.listen(0, () => ok({ srv, url: `http://127.0.0.1:${srv.address().port}` })));
}

async function get(path, tok, allowed) {
  const { srv, url } = await site(allowed);
  try {
    const r = await fetch(url + path, { headers: tok ? { "x-goog-iap-jwt-assertion": tok } : {} });
    return { status: r.status, headers: r.headers, text: await r.text() };
  } finally {
    srv.close();
  }
}

test("서명 없으면 막음 (IAP가 꺼져 공개돼도)", async () => {
  assert.equal((await get("/")).status, 403);
});
test("다른 계정이면 막음", async () => {
  assert.equal((await get("/", token({ email: "other@example.com" }))).status, 403);
});
test("다른 키로 서명했으면 막음", async () => {
  const other = generateKeyPairSync("ec", { namedCurve: "P-256" }).privateKey;
  assert.equal((await get("/", token({}, "k1", other))).status, 403);
});
test("기한 지난 서명은 막음", async () => {
  assert.equal((await get("/", token({ exp: NOW - 100 }))).status, 403);
});
test("ALLOWED_EMAIL 이 비면 아무에게도 열지 않음", async () => {
  assert.equal((await get("/", token(), "")).status, 403);
});
test("본인이면 첫 화면을 매번 새로 받게 함", async () => {
  const r = await get("/", token());
  assert.equal(r.status, 200);
  assert.equal(r.text, "<p>hi</p>");
  assert.equal(r.headers.get("cache-control"), "no-store");
  assert.match(r.headers.get("content-security-policy"), /connect-src 'self'/);
});
test("해시 붙은 파일은 오래 둠", async () => {
  const r = await get("/assets/index-DZ-TLYoT.js", token());
  assert.equal(r.status, 200);
  assert.match(r.headers.get("cache-control"), /immutable/);
});
test("/api/me 는 로그인 이메일", async () => {
  const r = await get("/api/me", token({ email: "Me@Example.com" }));
  assert.deepEqual(JSON.parse(r.text), { email: "me@example.com" });
});
test("자료를 받는 길(POST)은 없음", async () => {
  const { srv, url } = await site();
  try {
    const r = await fetch(url + "/", { method: "POST", body: "x", headers: { "x-goog-iap-jwt-assertion": token() } });
    assert.equal(r.status, 405);
  } finally {
    srv.close();
  }
});
test("폴더 밖 파일은 못 읽음", async () => {
  const r = await get("/..%2f..%2fetc%2fpasswd", token());
  assert.notEqual(r.text.includes("root:"), true);
});
test("verifyIapJwt 는 모양이 틀린 글을 거절", () => {
  assert.equal(verifyIapJwt("a.b", KEYS, NOW), null);
  assert.equal(verifyIapJwt(undefined, KEYS, NOW), null);
});
