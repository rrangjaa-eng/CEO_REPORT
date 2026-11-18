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
<b>수정 모드</b><span style="opacity:.85">글자·숫자를 눌러 바로 고치세요. 원래 보고서는 그대로 남습니다. 고친 숫자의 합계·비율·근거자료는 다시 계산되지 않습니다.</span>
<span style="flex:1"></span><span id="edit-msg" style="opacity:.95"></span>
<button id="edit-save" style="font:bold 14px 'Malgun Gothic',sans-serif;padding:6px 14px;border:0;border-radius:4px;background:#fff;color:#1f4e8c;cursor:pointer">저장하고 PDF 만들기</button>
<button id="edit-close" style="font:14px 'Malgun Gothic',sans-serif;padding:6px 12px;border:1px solid #fff;border-radius:4px;background:transparent;color:#fff;cursor:pointer">끝내기</button>
</div>
<div id="edit-stale" contenteditable="false" style="display:none;position:sticky;top:48px;z-index:9998;padding:10px 16px;background:#fde2e2;color:#7f1d1d;font:14px 'Malgun Gothic',sans-serif">
<b>원본 보고가 다시 만들어졌습니다.</b> 이 화면의 숫자는 예전 것이라 저장하지 않습니다. 아래 고친 곳을 복사해 두고, 이 창을 닫은 뒤 수정 모드를 다시 열어 옮기세요.
<button id="edit-copy" style="margin-left:8px;font:13px 'Malgun Gothic',sans-serif">고친 곳 복사</button>
<pre id="edit-list" style="white-space:pre-wrap;margin:6px 0 0;font:13px 'Malgun Gothic',sans-serif"></pre></div>
<style>@media print{#edit-bar,#edit-stale{display:none!important}}[contenteditable=true]:focus{outline:2px dashed #1f4e8c55}</style>
<script>
(function(){
  var KEY=%(key)s, dirty=false, stale=false;
  var first=document.body.innerText.split('\n');
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
  // 편의성 48 (2026-11-17): 원본이 바뀌면 저장할 때가 아니라 바로 알리고, 고친 곳 목록을 보여 새 보고로 옮기기 쉽게
  function edited(){
    var seen={}; first.forEach(function(t){seen[t]=1;});
    return document.body.innerText.split('\n').filter(function(t){t=t.trim(); return t && !seen[t] && t.indexOf('수정 모드')<0;}).slice(0,40);
  }
  function showStale(){
    stale=true; var box=document.getElementById('edit-stale'); box.style.display='block';
    var l=edited(); document.getElementById('edit-list').textContent=l.length?l.join('\n'):'(아직 고친 곳 없음)';
    document.getElementById('edit-save').disabled=true;
  }
  document.getElementById('edit-copy').onclick=function(){
    var t=document.getElementById('edit-list').textContent;
    if(navigator.clipboard) navigator.clipboard.writeText(t); msg('고친 곳을 복사했습니다');
  };
  setInterval(function(){ if(stale) return;
    var x=new XMLHttpRequest(); x.open('GET','/state?k='+KEY);
    x.onload=function(){try{if(JSON.parse(x.responseText).stale) showStale();}catch(e){}}; x.send();
  },10000);
  document.getElementById('edit-save').onclick=function(){
    msg('저장하고 PDF를 만드는 중…'); this.disabled=true; var btn=this;
    post('/save',clean(),function(st,r){btn.disabled=false;
      if(st===200&&r.ok){dirty=false; msg('저장함: '+r.pdf+' (PDF가 열립니다)');}
      else if(r.html){dirty=false; msg(r.msg);}
      else {if(r.stale) showStale(); msg('저장하지 못함: '+(r.msg||'프로그램 창이 닫혔는지 확인하세요'));}});
  };
  document.getElementById('edit-close').onclick=function(){
    if(dirty&&!confirm('저장하지 않은 내용이 있습니다. 그래도 끝낼까요?'))return;
    post('/close','',function(){msg('수정 모드를 끝냈습니다. 이 창을 닫으세요.');
      document.body.removeAttribute('contenteditable');});
  };
  window.addEventListener('beforeunload',function(e){if(dirty){e.preventDefault();e.returnValue='';}});
})();
</script>""" + END


def _sig(path):
    """파일의 (바뀐 시각, 크기) — 없으면 None."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def edited_path(html_path):
    base, ext = os.path.splitext(html_path)
    return base + SUFFIX + ext


def original_path(html_path):
    base, ext = os.path.splitext(html_path)
    return base[:-len(SUFFIX)] + ext if base.endswith(SUFFIX) else html_path


# 2차 전수조사 J3 (2026-11-18): 손으로 고친 보고는 맨 아래 작은 한 줄로 알린다 — 받는 사람이 계산 값인지 고친 값인지 알게.
# 고친 곳이 없으면 붙이지 않는다. (결정 카드 2026-11-18 — 답이 '표시 안 함'이면 MARK = False)
MARK = True
_MARK_RE = re.compile(r"<div id=\"edit-mark\".*?</div>", re.S)


def unmark(page):
    return _MARK_RE.sub("", page or "")


def mark(orig_page, page, today=None):
    """고친 보고에 '손으로 고친 곳 N곳' 한 줄을 붙인다 (</body> 앞). 고친 곳이 없거나 MARK 가 꺼져 있으면 표시 없이."""
    page = unmark(page)
    if not MARK:
        return page
    n = len(changes(orig_page, page, limit=100000))
    if not n:
        return page
    import datetime as _dt
    line = ("<div id=\"edit-mark\" style=\"margin:10px 0 0;font-size:10.5px;color:#556070;text-align:right\">"
            "손으로 고친 곳 %d곳 (%s) · 고친 숫자의 합계와 비율은 다시 계산하지 않음</div>" % (n, (today or _dt.date.today()).isoformat()))
    i = page.lower().rfind("</body>")
    return page + line if i < 0 else page[:i] + line + page[i:]


def _texts(page):
    """보이는 글 조각들 (style·script 빼고, 공백 하나로)."""
    import html as _h
    page = unmark(strip(page or ""))
    page = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", page, flags=re.S | re.I)
    page = page.split("<body", 1)[-1]
    out = []
    for t in re.findall(r">([^<]+)<", page):
        t = re.sub(r"\s+", " ", _h.unescape(t)).strip()
        if t:
            out.append(t)
    return out


def changes(orig_page, edited_page, limit=30):
    """손으로 고친 곳 [(원래 글, 고친 글)] — 2차 P4-2 (2026-11-15): 고친 대표 보고와 근거자료(고치기 전 계산)가 다를 때 알리려고."""
    import difflib
    a, b = _texts(orig_page), _texts(edited_page)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            out.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return out[:limit]


def edits_for(orig_html_path):
    """원래 대표 보고 HTML 경로 -> 쓰이는 _수정 판이 있으면 고친 곳 목록, 없으면 None (원래보다 오래된 _수정 은 쓰이지 않으니 None)."""
    ed = edited_path(orig_html_path)
    try:
        if not os.path.isfile(ed) or os.path.getmtime(ed) < os.path.getmtime(orig_html_path):
            return None
        with open(orig_html_path, encoding="utf-8") as f:
            a = f.read()
        with open(ed, encoding="utf-8") as f:
            b = f.read()
    except (OSError, ValueError):
        return None
    return changes(a, b)


def latest_report(output_dir, kind):
    """kind(주간·월간)의 가장 최근 대표 보고 HTML. (원래 파일, 고칠 파일) — 원래보다 새 _수정 이 있으면 그걸 이어서 고친다."""
    found = glob.glob(os.path.join(output_dir, "*_%s_대표보고.html" % kind))
    if not found:
        return None, None
    # 2차 P4-7 (2026-11-15): '방금 만든 보고'(winstate.latest_reports)와 같게 가장 최근에 만든 것 — 예전엔 이름(기준일) 순이라
    # 11/8 보고를 방금 다시 만들어도 11/15 보고를 열었다
    orig = max(found, key=lambda p: (os.path.getmtime(p), p))
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
        # P3-4·P4-3 (2026-11-15): 수정 모드를 연 뒤 원본 보고가 다시 만들어지면(막힘 안내로 바뀐 것 포함) 열린 화면의 옛 숫자로
        # PDF 를 만들지 않는다 — 원본 파일의 바뀐 시각·크기를 기억해 저장 때 견준다.
        self.orig = original_path(save_html)
        self.orig_sig = _sig(self.orig)

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
                if urlparse(self.path).path == "/state":   # 편의성 48: 원본이 바뀌었는지 화면이 묻는다
                    path, ok = self._key_ok()
                    if not ok:
                        return self._send(403, "{}")
                    return self._send(200, json.dumps({"stale": sess.stale()}))
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
                self._send(200 if ok else 500, json.dumps({"ok": ok, "msg": text, "pdf": os.path.basename(pdf or ""),
                                                           "html": text.startswith("HTML 저장됨"), "stale": sess.stale()},
                                                          ensure_ascii=False))
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.url

    def stale(self):
        """수정 모드를 연 뒤 원본 보고가 다시 만들어졌는가."""
        return _sig(self.orig) != self.orig_sig

    def save(self, page):
        page = strip(page)
        if "</html>" not in page.lower():
            return False, "보고서 내용이 아님", None
        if _sig(self.orig) != self.orig_sig:
            msg = ("원본 보고가 수정 모드를 연 뒤 다시 만들어져(또는 자료 확인으로 막혀) 이 화면의 숫자가 예전 것일 수 있어 저장하지 않음 "
                   "— 이 창을 닫고 수정 모드를 다시 여세요")
            self.on_saved(None, msg)
            return False, msg, None
        try:
            with open(self.orig, encoding="utf-8") as f:
                page = mark(f.read(), page)
        except (OSError, ValueError):
            page = unmark(page)   # 원본을 못 읽으면 고친 곳을 셀 수 없어 표시 없이 (저장은 그대로)
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
        if err:   # 편의성 32: HTML 은 저장됐고 PDF 만 못 만든 것을 '저장하지 못함'과 구분
            self.on_saved(None, "%s 저장함, PDF는 못 만듦: %s" % (os.path.basename(self.dst), err))
            return False, "HTML 저장됨 / PDF 못 만듦: %s" % err, None
        self.on_saved(pdf, "저장함: %s" % os.path.basename(pdf))
        return True, "저장함", pdf

    def stop(self):
        if self.server:
            srv, self.server = self.server, None
            srv.shutdown()
            srv.server_close()
            self.on_closed()

