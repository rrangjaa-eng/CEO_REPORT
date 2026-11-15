"""수정 모드 (사용자 2026-11-04: 대표 주간·월간 보고를 손으로 고칠 수 있게).

만든 대표 보고 HTML 을 브라우저에서 글자를 바로 고칠 수 있게 연다. 위쪽 띠의 '저장하고 PDF 만들기'를 누르면
같은 이름에 _수정 을 붙여 HTML·PDF 로 저장한다 (원래 보고서는 그대로 둔다).
  · 이 컴퓨터 안에서만 받는다 (127.0.0.1, 실행마다 바뀌는 열쇠가 주소에 있어야 저장됨)
  · 보고서를 다시 만들면(주간·월간 보고 버튼) 원래 보고서가 새로 생기고, 그보다 오래된 _수정 은 쓰지 않는다
"""
import glob
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SUFFIX = "_수정"
MAX_BODY = 20 * 1024 * 1024
START, END = "<!--수정모드-시작-->", "<!--수정모드-끝-->"

_BAR = START + """<div id="edit-bar" contenteditable="false" style="position:sticky;top:0;z-index:9999;display:flex;gap:10px;
align-items:center;flex-wrap:wrap;padding:10px 16px;background:#1f4e8c;color:#fff;font:14px 'Malgun Gothic',sans-serif">
<b>수정 모드</b><span style="opacity:.85">글자·숫자를 눌러 바로 고치세요. 원래 보고서는 그대로 남습니다.</span>
<span style="flex:1"></span><span id="edit-msg" style="opacity:.95"></span>
<button id="edit-save" style="font:bold 14px 'Malgun Gothic',sans-serif;padding:6px 14px;border:0;border-radius:4px;background:#fff;color:#1f4e8c;cursor:pointer">저장하고 PDF 만들기</button>
<button id="edit-close" style="font:14px 'Malgun Gothic',sans-serif;padding:6px 12px;border:1px solid #fff;border-radius:4px;background:transparent;color:#fff;cursor:pointer">끝내기</button>
</div>
<style>@media print{#edit-bar{display:none!important}}[contenteditable=true]:focus{outline:2px dashed #1f4e8c55}</style>
<script>
(function(){
  var KEY=%(key)s, dirty=false;
  document.body.setAttribute('contenteditable','true');
  document.body.setAttribute('spellcheck','false');
  document.body.addEventListener('input',function(){dirty=true;msg('고친 내용이 아직 저장되지 않았습니다');});
  function msg(t){document.getElementById('edit-msg').textContent=t;}
  function clean(){
    var doc=document.documentElement.cloneNode(true);
    var b=doc.querySelector('body'); b.removeAttribute('contenteditable'); b.removeAttribute('spellcheck');
    ['#edit-bar','#edit-style','#edit-script'].forEach(function(s){var e=doc.querySelector(s); if(e) e.remove();});
    return '<!doctype html>'+doc.outerHTML;
  }
  function post(path,body,done){
    var x=new XMLHttpRequest(); x.open('POST',path+'?k='+KEY); x.setRequestHeader('Content-Type','text/html; charset=utf-8');
    x.onload=function(){var r={}; try{r=JSON.parse(x.responseText);}catch(e){} done(x.status,r);};
    x.onerror=function(){done(0,{});}; x.send(body);
  }
  document.getElementById('edit-save').onclick=function(){
    msg('저장하고 PDF를 만드는 중…'); this.disabled=true; var btn=this;
    post('/save',clean(),function(st,r){btn.disabled=false;
      if(st===200&&r.ok){dirty=false; msg('저장함: '+r.pdf+' (PDF가 열립니다)');}
      else msg('저장하지 못함: '+(r.msg||'프로그램 창이 닫혔는지 확인하세요'));});
  };
  document.getElementById('edit-close').onclick=function(){
    if(dirty&&!confirm('저장하지 않은 내용이 있습니다. 그래도 끝낼까요?'))return;
    post('/close','',function(){msg('수정 모드를 끝냈습니다. 이 창을 닫으세요.');
      document.body.removeAttribute('contenteditable');});
  };
  window.addEventListener('beforeunload',function(e){if(dirty){e.preventDefault();e.returnValue='';}});
})();
</script>""" + END


def edited_path(html_path):
    base, ext = os.path.splitext(html_path)
    return base + SUFFIX + ext


def original_path(html_path):
    base, ext = os.path.splitext(html_path)
    return base[:-len(SUFFIX)] + ext if base.endswith(SUFFIX) else html_path


def latest_report(output_dir, kind):
    """kind(주간·월간)의 가장 최근 대표 보고 HTML. (원래 파일, 고칠 파일) — 원래보다 새 _수정 이 있으면 그걸 이어서 고친다."""
    found = sorted(glob.glob(os.path.join(output_dir, "*_%s_대표보고.html" % kind)))
    if not found:
        return None, None
    orig = found[-1]
    ed = edited_path(orig)
    if os.path.isfile(ed) and os.path.getmtime(ed) >= os.path.getmtime(orig):
        return orig, ed
    return orig, orig


def inject(page, key):
    """보고서 HTML 에 수정 띠를 넣는다 (body 여는 태그 바로 뒤)."""
    bar = _BAR % {"key": json.dumps(key)}
    bar = bar.replace("<style>@media print", "<style id=\"edit-style\">@media print", 1)
    bar = bar.replace("<script>", "<script id=\"edit-script\">", 1)
    m = re.search(r"<body[^>]*>", page, re.I)
    if not m:
        return bar + page
    return page[:m.end()] + bar + page[m.end():]


def strip(page):
    """저장할 때: 수정 띠와 고치기 표시를 모두 뺀다 (브라우저가 못 뺀 것까지)."""
    page = re.sub(re.escape(START) + ".*?" + re.escape(END), "", page, flags=re.S)
    for sel in ("edit-bar", "edit-style", "edit-script"):
        page = re.sub(r"<(div|style|script)[^>]*id=\"%s\".*?</\1>" % sel, "", page, flags=re.S)
    page = re.sub(r"\s(contenteditable|spellcheck)=\"[^\"]*\"", "", page)
    return page


class Session(object):
    """수정 모드 한 번. start() 후 url 을 브라우저로 연다. 저장할 때마다 on_saved(pdf 또는 None, 글)를 부른다."""

    def __init__(self, src_html, save_html, make_pdf, on_saved=None, on_closed=None):
        self.src, self.dst = src_html, save_html
        self.make_pdf = make_pdf            # (html, pdf) -> 오류 글 또는 None
        self.on_saved = on_saved or (lambda pdf, text: None)
        self.on_closed = on_closed or (lambda: None)
        self.key = secrets.token_urlsafe(16)
        self.server = None
        self.lock = threading.Lock()

    @property
    def url(self):
        return "http://127.0.0.1:%d/%s" % (self.server.server_address[1], self.key)

    def start(self):
        sess = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _key_ok(self):
                u = urlparse(self.path)
                q = dict(p.split("=", 1) for p in u.query.split("&") if "=" in p)
                return u.path, secrets.compare_digest(q.get("k", ""), sess.key)

            def do_GET(self):
                if urlparse(self.path).path != "/" + sess.key:
                    return self._send(404, "{}")
                with open(sess.src, encoding="utf-8") as f:
                    page = f.read()
                self._send(200, inject(page, sess.key), "text/html; charset=utf-8")

            def do_POST(self):
                path, ok = self._key_ok()
                if not ok or path not in ("/save", "/close"):
                    return self._send(403, json.dumps({"ok": False, "msg": "열쇠가 맞지 않음"}))
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    return self._send(413, json.dumps({"ok": False, "msg": "너무 큼"}))
                body = self.rfile.read(n).decode("utf-8", "replace")
                if path == "/close":
                    self._send(200, json.dumps({"ok": True}))
                    threading.Thread(target=sess.stop, daemon=True).start()
                    return None
                ok, text, pdf = sess.save(body)
                self._send(200 if ok else 500, json.dumps({"ok": ok, "msg": text, "pdf": os.path.basename(pdf or "")},
                                                          ensure_ascii=False))
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.url

    def save(self, page):
        page = strip(page)
        if "</html>" not in page.lower():
            return False, "보고서 내용이 아님", None
        with self.lock:
            tmp = self.dst + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(page)
                os.replace(tmp, self.dst)
            except OSError as e:   # 파일이 열려 있거나 폴더가 없으면 화면에 알린다 (코덱스 검토 2026-11-14)
                msg = "저장하지 못함 (%s) — 같은 파일이 열려 있으면 닫고 다시 저장하세요" % type(e).__name__
                self.on_saved(None, msg)
                return False, msg, None
            self.src = self.dst              # 다시 열면 고친 것부터
            pdf = os.path.splitext(self.dst)[0] + ".pdf"
            try:
                err = self.make_pdf(self.dst, pdf)
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, e)
        if err:
            self.on_saved(None, "%s 저장함, PDF는 못 만듦: %s" % (os.path.basename(self.dst), err))
            return False, err, None
        self.on_saved(pdf, "저장함: %s" % os.path.basename(pdf))
        return True, "저장함", pdf

    def stop(self):
        if self.server:
            srv, self.server = self.server, None
            srv.shutdown()
            srv.server_close()
            self.on_closed()

