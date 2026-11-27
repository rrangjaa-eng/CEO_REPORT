// CEO 보고 사이트 서버 (Cloud Run). 화면 파일만 내려 주고, 회사 자료를 받는 길은 없다(GET·HEAD만).
// 본인 확인: IAP 서명이 맞고 그 이메일이 ALLOWED_EMAIL 과 같을 때만 응답한다.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { iapKeys, verifyIapJwt } from "./iap.mjs";

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
  ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8" };

export const SECURITY_HEADERS = {
  // 자기 주소 밖으로는 아무것도 보내거나 불러오지 못하게 (회사 자료가 브라우저 밖으로 나가지 않게)
  "Content-Security-Policy": "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; " +
    "font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
};

function send(res, code, body, headers = {}) {
  res.writeHead(code, { ...SECURITY_HEADERS, ...headers });
  res.end(body);
}

/** 사이트 처리기. opts: { root, allowed, audience, keys: () => Promise<keys>, now: () => sec } */
export function handler(opts) {
  const root = resolve(opts.root);
  const allowed = String(opts.allowed || "").trim().toLowerCase();
  return async (req, res) => {
    try {
      if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, "", { Allow: "GET, HEAD" });
      if (!allowed) return send(res, 403, "ALLOWED_EMAIL 이 설정되지 않아 열지 않음", { "Content-Type": "text/plain; charset=utf-8" });
      if (!opts.audience) return send(res, 403, "IAP_AUDIENCE 가 설정되지 않아 열지 않음", { "Content-Type": "text/plain; charset=utf-8" });
      const who = verifyIapJwt(req.headers["x-goog-iap-jwt-assertion"], await opts.keys(), opts.now ? opts.now() : undefined, opts.audience);
      if (!who || who.email !== allowed) return send(res, 403, "허용되지 않은 접속", { "Content-Type": "text/plain; charset=utf-8" });
      const url = new URL(req.url, "http://x");
      if (url.pathname === "/api/me") {
        return send(res, 200, JSON.stringify({ email: who.email }), { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
      }
      let rel;
      try {
        rel = decodeURIComponent(url.pathname);
      } catch {
        return send(res, 400, "잘못된 주소", { "Content-Type": "text/plain; charset=utf-8" });
      }
      if (rel.endsWith("/")) rel += "index.html";
      const file = normalize(join(root, rel));
      if (file !== root && !file.startsWith(root + sep)) return send(res, 404, "");
      let path = file;
      try {
        if (!(await stat(path)).isFile()) throw new Error("dir");
      } catch {
        if (extname(rel)) return send(res, 404, "없음", { "Content-Type": "text/plain; charset=utf-8" });
        path = join(root, "index.html");   // 화면 주소는 모두 index.html
      }
      const body = await readFile(path);
      const hashed = /\/assets\/[^/]+-[A-Za-z0-9_-]{8,}\.[a-z0-9]+$/.test(path.split(sep).join("/"));
      return send(res, 200, req.method === "HEAD" ? "" : body, {
        "Content-Type": TYPES[extname(path)] || "application/octet-stream",
        // 새로 올린 뒤 옛 계산 코드가 남지 않게: 첫 화면은 매번 새로, 이름에 해시가 붙은 파일만 오래 둠
        "Cache-Control": hashed ? "public, max-age=31536000, immutable" : "no-store",
      });
    } catch (e) {
      return send(res, 500, "서버 오류", { "Content-Type": "text/plain; charset=utf-8" });
    }
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 8080);
  const root = process.env.WEB_ROOT || join(fileURLToPath(new URL(".", import.meta.url)), "..", "web", "dist");
  createServer(handler({ root, allowed: process.env.ALLOWED_EMAIL, audience: process.env.IAP_AUDIENCE, keys: () => iapKeys() }))
    .listen(port, () => console.log(`listening on ${port}`));
}
