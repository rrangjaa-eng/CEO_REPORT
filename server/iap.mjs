// IAP(구글 로그인 관문)가 붙여 보내는 서명(x-goog-iap-jwt-assertion)을 확인한다.
// IAP가 꺼져 사이트가 공개되더라도 서명이 없거나 다른 계정이면 서버가 아무것도 내주지 않게 하는 두 번째 자물쇠.
import { createPublicKey, verify } from "node:crypto";

export const IAP_ISSUER = "https://cloud.google.com/iap";
export const IAP_KEYS_URL = "https://www.gstatic.com/iap/verify/public_key-jwk";

const b64u = (s) => Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64");

/** -> { email } 또는 null. keys: { kid: jwk }. audience: 이 서비스의 IAP aud (/projects/<번호>/locations/<지역>/services/<이름>) */
export function verifyIapJwt(token, keys, nowSec = Math.floor(Date.now() / 1000), audience) {
  if (typeof token !== "string" || !audience) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  let header, claims;
  try {
    header = JSON.parse(b64u(parts[0]).toString("utf8"));
    claims = JSON.parse(b64u(parts[1]).toString("utf8"));
  } catch {
    return null;
  }
  if (header.alg !== "ES256" || typeof header.kid !== "string" || !Object.hasOwn(keys, header.kid)) return null;
  const ok = verify("sha256", Buffer.from(parts[0] + "." + parts[1]),
    { key: createPublicKey({ key: keys[header.kid], format: "jwk" }), dsaEncoding: "ieee-p1363" }, b64u(parts[2]));
  if (!ok) return null;
  if (claims.iss !== IAP_ISSUER) return null;
  if (claims.aud !== audience) { // 다른 IAP 앱에 발급된 서명은 받지 않음 (설정이 틀렸을 때 로그로 알 수 있게 aud 만 남김)
    console.warn("IAP aud 다름: 받은 값 %s, 기대 %s", String(claims.aud), audience);
    return null;
  }
  if (typeof claims.exp !== "number" || claims.exp < nowSec - 30) return null;
  if (typeof claims.iat !== "number" || claims.iat > nowSec + 30) return null;
  if (typeof claims.email !== "string" || !claims.email) return null;
  return { email: claims.email.toLowerCase() };
}

let cache = { at: 0, keys: null };

/** 구글 공개 키를 받아 1시간 둔다. */
export async function iapKeys(fetchImpl = fetch, nowMs = Date.now()) {
  if (cache.keys && nowMs - cache.at < 3600_000) return cache.keys;
  const r = await fetchImpl(IAP_KEYS_URL);
  if (!r.ok) throw new Error("IAP 공개 키를 받지 못함: " + r.status);
  const body = await r.json();
  const keys = Object.fromEntries((body.keys || []).map((k) => [k.kid, k]));
  cache = { at: nowMs, keys };
  return keys;
}
