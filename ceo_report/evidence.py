"""근거자료만 따로 (사용자 2026-11-03): 대표가 근거 번호로 요청하면 경영관리용 보고서에서 그 번호의 근거만 뽑아 한 문서로.

이미 만든 경영관리용 HTML에서 뽑는다 (대표에게 낸 보고서와 같은 숫자). 번호 → 첫 화면 근거 묶음의 id='ev-번호' 블록,
또는 상세 장 (<h2 id='sN'>부터 다음 <h2> 앞까지)."""
import html as _html
import re

NUM = re.compile(r"^\d+-\d+$")


def parse_nums(text):
    """'1-1, 3-2 1-1' -> ['1-1', '3-2'] (순서 유지, 중복 제거). 형식이 틀린 번호는 ValueError."""
    out = []
    for t in re.split(r"[,\s·]+", (text or "").replace("근거", " ").strip()):
        if not t:
            continue
        if not NUM.match(t):
            raise ValueError("근거 번호 형식 오류: %s (예: 1-1, 3-2)" % t)
        if t not in out:
            out.append(t)
    if not out:
        raise ValueError("근거 번호를 넣으세요 (예: 1-1, 3-2)")
    return out


def index_of(mgmt_html):
    """경영관리용 HTML의 근거 번호표 -> [(번호, 대표용 항목, 'ev-번호' 또는 'sN')]."""
    rows = re.findall(r"<tr><td><b>근거 (\d+-\d+)</b></td><td>(.*?)</td><td><a href='#([^']+)'>", mgmt_html)
    return [(n, _html.unescape(t), w) for n, t, w in rows]


def _block(mgmt_html, target):
    if target.startswith("ev-"):   # render._ev_block 이 끝에 <!-- /ev-번호 --> 를 붙인다
        m = re.search(r"<div class='evb' id='%s'>.*?<!-- /%s -->" % (re.escape(target), re.escape(target)), mgmt_html, re.S)
        return m.group(0) if m else None
    # 영역별 보기(2026-11-11): 장 끝에 이전·다음 단추(apager)와 </section> 이 붙는다 → 그 앞에서 끊는다
    m = re.search(r"<h2 id='%s'>.*?(?=<h2 id=|<div class='apager'>|</section>|</div></body>|$)" % re.escape(target), mgmt_html, re.S)
    return m.group(0) if m else None


def build(mgmt_html, nums, who="대표", when=""):
    """뽑은 근거 문서 HTML. 모르는 번호는 ValueError (있는 번호를 알려 준다)."""
    idx = {n: (t, w) for n, t, w in index_of(mgmt_html)}
    bad = [n for n in nums if n not in idx]
    if bad:
        raise ValueError("이 보고서에 없는 근거 번호: %s (있는 번호: %s)" % (", ".join(bad), ", ".join(idx) or "없음"))
    head = mgmt_html.split("<body>")[0]
    title = re.search(r"<title>(.*?)</title>", head, re.S)
    name = title.group(1).replace("경영관리 보고", "근거자료") if title else "근거자료"
    head = re.sub(r"<title>.*?</title>", "<title>%s</title>" % name, head, flags=re.S)
    rows = "".join("<tr><td><b>근거 %s</b></td><td>%s</td></tr>" % (n, _html.escape(idx[n][0])) for n in nums)
    parts = ["<div class='wrap'><h1>%s</h1><div class='meta'>요청: %s%s · 제출: 경영관리</div>" % (
        _html.escape(name), _html.escape(who), (" · " + _html.escape(when)) if when else ""),
        "<table class='pt evt' style='margin:10px 0 16px'><thead><tr><th>번호</th><th>대표용 항목</th></tr></thead><tbody>%s</tbody></table>" % rows]
    seen = set()
    for n in nums:
        t, w = idx[n]
        if w in seen:   # 같은 장을 가리키는 번호는 한 번만 싣는다
            parts.append("<div class='note'>근거 %s 는 위와 같은 자리</div>" % n)
            continue
        seen.add(w)
        body = _block(mgmt_html, w)
        if w.startswith("s"):
            body = "<div class='evh'>근거 %s · %s</div>%s" % (n, _html.escape(t), body or "")
        parts.append("<div class='evpart'>%s</div>" % (body or "<div class='note'>근거 %s: 자리를 찾지 못함</div>" % n))
    parts.append("</div>")
    return head + "<body>" + "".join(parts) + "</body></html>"
