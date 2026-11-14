// 위하고 화면(MAIN world)에서 분개장·자금계획입력 [조회] 응답만 엿본다. 요청을 새로 보내거나 바꾸지 않는다 (읽기 전용).
(() => {
  if (window.__ceoReportHook) return;
  window.__ceoReportHook = true;
  const WATCH = [{kind: "분개장", re: /\/smarta\/sabk0113\/?(\?|$)/},
                 {kind: "자금계획목록", re: /\/smarta\/safm0102\/?(\?|$)/},
                 {kind: "자금계획상세", re: /\/smarta\/safm0102\/detail\/?(\?|$)/}];
  const kindOf = (url) => { for (const w of WATCH) if (w.re.test(String(url))) return w.kind; return null; };
  const KEYS = ["start_date", "end_date", "gisu", "date", "cd_fitem"];
  const params = (url, body) => {   // 기간·날짜·기수·자금항목만 남긴다 (서명·세션 값은 담지 않음)
    const out = {};
    for (const src of [typeof body === "string" ? body : "", String(url).split("?")[1] || ""]) {
      try {
        const p = new URLSearchParams(src);
        for (const k of KEYS) if (p.has(k) && !(k in out)) out[k] = p.get(k);
      } catch (e) { /* 무시 */ }
    }
    return out;
  };
  // 결산 자료 받기 (사용자 2026-11-12): 확장이 '받을 준비'를 알린 동안만 SmartA 화면의 다른 [조회] 응답도 엿본다 (읽기 전용)
  let armUntil = 0;
  window.addEventListener("message", (e) => {
    if (e.source === window && e.data && e.data.__ceoArm === 1) armUntil = Date.now() + (+e.data.ms || 15000);
  });
  const isApi = (url) => /\/smarta\/[a-z0-9]+\/|\/superbook\/collectingdata\//i.test(String(url));   // 자료수집현황은 superbook 경로
  const pathOf = (url) => { try { return new URL(String(url), location.href).pathname; } catch (e) { return ""; } };
  const postRaw = (url, text) => window.postMessage({__ceoReport: 1, kind: "결산원본", path: pathOf(url), params: {}, text}, location.origin);
  const post = (kind, url, body, text) => window.postMessage({__ceoReport: 1, kind, params: params(url, body), text}, location.origin);

  const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__ceoUrl = u; return open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    const kind = kindOf(this.__ceoUrl);
    if (kind) this.addEventListener("load", () => {
      if (this.status === 200 && (this.responseType === "" || this.responseType === "text")) post(kind, this.__ceoUrl, body, this.responseText);
    });
    else if (isApi(this.__ceoUrl)) this.addEventListener("load", () => {
      if (Date.now() < armUntil && this.status === 200 && (this.responseType === "" || this.responseType === "text")) postRaw(this.__ceoUrl, this.responseText);
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
      else if (!kind && res.ok && Date.now() < armUntil && isApi(url)) postRaw(url, await res.clone().text());
    } catch (e) { /* 무시 */ }
    return res;
  };
})();
