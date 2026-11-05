// 위하고 화면(MAIN world)에서 분개장 [조회] 응답만 엿본다. 요청을 새로 보내거나 바꾸지 않는다 (읽기 전용).
(() => {
  if (window.__ceoReportHook) return;
  window.__ceoReportHook = true;
  const WATCH = [{kind: "분개장", re: /\/smarta\/sabk0113\/?(\?|$)/}];
  const kindOf = (url) => { for (const w of WATCH) if (w.re.test(String(url))) return w.kind; return null; };
  const params = (body) => {   // 기간·기수만 남긴다 (서명·세션 값은 담지 않음)
    const out = {};
    try {
      const p = new URLSearchParams(typeof body === "string" ? body : "");
      for (const k of ["start_date", "end_date", "gisu"]) if (p.has(k)) out[k] = p.get(k);
    } catch (e) { /* 무시 */ }
    return out;
  };
  const post = (kind, url, body, text) => window.postMessage({__ceoReport: 1, kind, params: params(body), text}, location.origin);

  const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__ceoUrl = u; return open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    const kind = kindOf(this.__ceoUrl);
    if (kind) this.addEventListener("load", () => {
      if (this.status === 200 && (this.responseType === "" || this.responseType === "text")) post(kind, this.__ceoUrl, body, this.responseText);
    });
    return send.apply(this, arguments);
  };
  const f = window.fetch;
  window.fetch = async function (input, init) {
    const res = await f.apply(this, arguments);
    try {
      const url = typeof input === "string" ? input : input.url;
      const kind = kindOf(url);
      if (kind && res.ok) post(kind, url, init && init.body, await res.clone().text());
    } catch (e) { /* 무시 */ }
    return res;
  };
})();
