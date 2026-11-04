"""인트라넷 읽기 전용 수집기.

규칙
- 읽기 전용: 허용 목록(check_url) 밖의 요청은 보내기 전에 막는다. 승인·삭제는 /confirm 같은
  GET 링크라서 요청 하나가 회사 자료를 바꿀 수 있다.
- ID·비밀번호·쿠키는 메모리에만 둔다. 파일·로그·예외 글에 남기지 않는다.
- 표준 라이브러리만 쓴다(urllib, http.cookiejar, html.parser, ssl).
"""
import collections
import html.parser
import http.cookiejar
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .snapshot import PAYMENT_COLUMNS, PROJECT_COLUMNS
from .util import mask_rrn

HOST = "intranet.plant8.co.kr"
BASE = "https://" + HOST
USER_AGENT = "Mozilla/5.0 (compatible; CEO_REPORT read-only collector)"

# 줄 값의 이름은 스냅숏 열과 같은 목록 하나를 쓴다(snapshot.py가 원본)
PAYMENT_KEYS = PAYMENT_COLUMNS
PROJECT_KEYS = PROJECT_COLUMNS

PAYMENT_HEADER = PAYMENT_KEYS + ["삭제"]
PROJECT_HEADER = ["", "번호", "클라이언트", "담당자", "PO번호", "행사일", "행사명", "국", "팀", "등록자",
                  "계산서", "사전견적", "견적금액", "실행가", "수익률", "", "담당자", "팀장", "관리팀",
                  "대표이사", "견적", "삭제"]
# 머리글 글자가 달라도 받는 자리: {칸 번호(0부터): 다른 표기}
PAYMENT_ALIASES = {2: ("파트너(페이먼트)",)}
PROJECT_ALIASES = {}

TOTAL_WORDS = ("total", "합계", "총계")


class BlockedRequest(Exception):
    """허용 목록 밖 요청. 글에는 방식과 경로만 담는다(조회 값은 담지 않는다)."""


class StructureMismatch(Exception):
    """인트라넷 화면 구조가 예상과 다름."""


class LoginFailed(Exception):
    """로그인이 안 됨."""


# ---------------------------------------------------------------------------
# 허용 목록
# ---------------------------------------------------------------------------

_DENY_WORDS = frozenset(["confirm", "logout", "delete", "del", "remove", "save", "insert", "update",
                         "modify", "write", "edit", "drop", "approve", "reject", "cancel"])
_DENY_KOREAN = ("삭제", "저장", "수정", "승인", "반려")
_PAGE_NAMES_ONE_BASED = ("page", "p", "pg", "cur_page", "curpage", "page_no", "pageno", "pagenum")
_PAGE_NAMES_ZERO_BASED = ("per_page", "offset", "start")
PAGE_NAMES = frozenset(_PAGE_NAMES_ONE_BASED + _PAGE_NAMES_ZERO_BASED)
FILTER_NAMES = {
    "payment": frozenset(["gyear", "team", "subteam", "project", "partner", "writer", "search", "confirm"]),
    "project": frozenset(["gyear", "team", "subteam", "search"]),
}
# 실제 쪽 링크(2026-11-04)에 빈 값으로만 붙어 오는 이름: 빈 값일 때만 받는다 (값이 있으면 다른 조회라 막음)
EMPTY_ONLY_NAMES = {
    "payment": frozenset(["pro_num"]),
    "project": frozenset(["client", "client_kor", "writer", "invoice", "confirm", "start_date", "end_date", "po_number"]),
}
_BAD_VALUE_FRAGMENTS = ("/confirm", "/logout", "://", "javascript:", "<", ">")
_LIST_RE = re.compile(r"^/(payment|project)/index(?:/([0-9]+))?/?$")   # 실제 프로젝트 쪽 링크: /project/index/?page=10
_DIGITS = re.compile(r"^[0-9]*$")


def _block(method, path, reason):
    shown = path if len(path) <= 80 else path[:80] + "..."
    raise BlockedRequest("허용 목록 밖 요청을 막음: %s %s (%s)" % (method, shown, reason))


def _path_of(url):
    try:
        return urllib.parse.urlsplit(url).path
    except ValueError:
        return ""


def _bad_value(value):
    low = value.lower()
    low2 = urllib.parse.unquote(value).lower()
    return any(frag in low or frag in low2 for frag in _BAD_VALUE_FRAGMENTS)


def check_url(method, url):
    """허용된 요청이면 조각(#...)을 뗀 주소를 돌려주고, 아니면 BlockedRequest.

    허용: GET / · POST /login/submit · GET /payment/index[/숫자] · GET /project/index[/숫자]
    (알려진 조회·쪽 이름만) · GET /project/payment?pro_num=숫자. 그 밖은 모두 막는다.
    """
    method = (method or "").upper()
    url = str(url)
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        _block(method, _path_of(url.strip()), "주소에 공백·제어 문자")
    url = url.split("#", 1)[0]
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        _block(method, _path_of(url), "주소 형식 오류")
    path = parts.path
    if parts.scheme != "https":
        _block(method, path, "https 아님")
    if "@" in parts.netloc:
        _block(method, path, "주소에 계정 정보")
    if host != HOST:
        _block(method, path, "다른 호스트")
    if port not in (None, 443):
        _block(method, path, "다른 포트")
    for bad in ("%", "\\", "//", "..", ";"):
        if bad in path:
            _block(method, path, "경로 형식")
    low = path.lower()
    if any(token in _DENY_WORDS for token in re.findall(r"[a-z0-9]+", low)) \
            or any(word in low for word in _DENY_KOREAN):
        _block(method, path, "승인·삭제·저장·로그아웃 계열 이름")
    if any(ord(ch) > 127 for ch in url):
        _block(method, path, "ASCII 아닌 문자")
    query = parts.query
    if method == "GET" and path == "/":
        if query:
            _block(method, path, "조회 값 허용 안 됨")
    elif method == "POST" and path == "/login/submit":
        if query:
            _block(method, path, "조회 값 허용 안 됨")
    elif method == "GET":
        m = _LIST_RE.match(path)
        if m:
            _check_list_query(method, path, m.group(1), query)
        elif path == "/project/payment":
            if not re.match(r"^pro_num=[0-9]+$", query):
                _block(method, path, "pro_num 숫자 하나만 허용")
        else:
            _block(method, path, "허용 경로 아님")
    else:
        _block(method, path, "허용 방식·경로 아님")
    return url


def _check_list_query(method, path, kind, query):
    if query == "":
        return
    known = FILTER_NAMES[kind] | PAGE_NAMES
    for pair in query.split("&"):
        if pair == "":
            _block(method, path, "빈 조회 항목")
        name, _, value = pair.partition("=")
        if name in EMPTY_ONLY_NAMES[kind] and name not in known:
            if value != "":
                _block(method, path, "빈 값만 허용되는 조회 이름: %s" % name[:30])
            continue
        if name not in known:
            _block(method, path, "알 수 없는 조회 이름: %s" % name[:30])
        if name in PAGE_NAMES:
            if not _DIGITS.match(value):
                _block(method, path, "쪽 값이 숫자 아님 (%s)" % name)
        elif len(value) > 100 or _bad_value(value):
            _block(method, path, "조회 값 거부 (%s)" % name)


# ---------------------------------------------------------------------------
# 요청 보내기
# ---------------------------------------------------------------------------

def _decode(raw, charset):
    if charset:
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


class SafeOpener(object):
    """check_url을 통과한 요청만 보낸다. 요청 사이에 delay초 쉰다. 자료를 파일로 저장하지 않는다."""

    def __init__(self, director, delay=0.3, sleep=time.sleep, timeout=30):
        self.director = director
        self.delay = delay
        self._sleep = sleep
        self.timeout = timeout
        self.calls_made = 0

    def _wait(self):
        if self.calls_made and self.delay:
            self._sleep(self.delay)
        self.calls_made += 1

    def _fetch(self, req):
        resp = self.director.open(req, timeout=self.timeout)
        try:
            raw = resp.read()
            status = resp.getcode()
            final_url = resp.geturl()
            charset = resp.headers.get_content_charset()
        finally:
            resp.close()
        return status, final_url, _decode(raw, charset)

    def get(self, url):
        """(상태코드, 최종 주소, 본문 글)"""
        url = check_url("GET", url)
        self._wait()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
        return self._fetch(req)

    def post(self, url, fields, follow=False):
        """follow=False면 3xx 응답을 그대로 돌려준다: (코드, Location 경로만, '')."""
        url = check_url("POST", url)
        body = urllib.parse.urlencode(fields).encode("ascii")
        self._wait()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"})
        if not follow:
            req.gsd_no_follow = True  # CheckedRedirectHandler가 보고 따라가지 않는다
        try:
            return self._fetch(req)
        except urllib.error.HTTPError as exc:
            if follow or not 300 <= exc.code < 400:
                raise
            location = exc.headers.get("Location") if exc.headers is not None else None
            exc.close()
            path = urllib.parse.urlsplit(location).path if location else None
            return exc.code, path or None, ""


class CheckedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """리디렉션 대상도 check_url을 통과해야 따라간다. 로그인 POST는 아예 따라가지 않는다."""

    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if getattr(req, "gsd_no_follow", False):
            return None
        check_url("GET", newurl)  # 막힌 대상이면 BlockedRequest — 요청은 나가지 않는다
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)


class AllowlistGuard(urllib.request.BaseHandler):
    """opener를 직접 부르는 경우까지 막는 마지막 문지기: 모든 요청을 보내기 전에 검사한다."""

    handler_order = 100

    def https_request(self, req):
        check_url(req.get_method(), req.full_url)
        return req

    http_request = https_request  # http는 check_url이 항상 막는다(닫힌 쪽으로 실패)


def make_opener(transport=None, proxies=None, delay=0.3, sleep=time.sleep, timeout=30):
    """처리기를 직접 골라 담은 opener. 기본 처리기(http, file, ftp, data)는 들어가지 않는다.

    transport: 시험용 가짜 https 처리기. 없으면 인증서·호스트 이름 검사를 켠 HTTPSHandler.
    proxies: None이면 시스템 설정, {}이면 프록시 없음.
    """
    director = urllib.request.OpenerDirector()
    director.addheaders = [("User-Agent", USER_AGENT)]
    jar = http.cookiejar.CookieJar()  # 메모리에만 — 파일로 저장하는 쿠키 저장소는 쓰지 않는다
    if transport is None:
        transport = urllib.request.HTTPSHandler(context=ssl.create_default_context())
    handlers = [
        AllowlistGuard(),
        urllib.request.ProxyHandler(proxies),
        transport,
        urllib.request.HTTPCookieProcessor(jar),
        CheckedRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.UnknownHandler(),
    ]
    for handler in handlers:
        director.add_handler(handler)
    return SafeOpener(director, delay=delay, sleep=sleep, timeout=timeout)


# ---------------------------------------------------------------------------
# HTML 읽기
# ---------------------------------------------------------------------------

_SPACE = re.compile(r"[\s ]+")


def _text(parts):
    return _SPACE.sub(" ", "".join(parts)).strip()


class Row(object):
    """표의 한 줄: cells(칸 글자), hrefs(칸마다 안에 있던 링크 주소 목록)."""

    def __init__(self, cells, hrefs, spans=None):
        self.cells = cells
        self.hrefs = hrefs
        self.spans = spans or [1] * len(cells)   # 칸마다 colspan (없으면 1)


class Table(object):
    def __init__(self):
        self.headers = []
        self.rows = []


class Page(object):
    def __init__(self):
        self.tables = []
        self.links = []  # (href, 글자) — 표 밖 링크 포함 전부
        self.forms = []  # {'name','id','action','method','inputs':[{'name','type','value'}]}


class _PageParser(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.page = Page()
        self._stack = []  # 표 중첩
        self._form = None
        self._anchor = None
        self._skip = 0

    # 표 보조
    def _close_cell(self, ctx):
        if ctx["cell"] is not None:
            ctx["cells"].append(ctx["cell"])
            ctx["cell"] = None

    def _close_row(self, ctx):
        self._close_cell(ctx)
        cells = ctx["cells"]
        if cells:
            if all(c["th"] for c in cells):
                if not ctx["table"].headers:
                    ctx["table"].headers = [_text(c["text"]) for c in cells]
            else:
                ctx["table"].rows.append(Row([_text(c["text"]) for c in cells],
                                             [list(c["hrefs"]) for c in cells],
                                             [c.get("span", 1) for c in cells]))
        ctx["cells"] = None

    def handle_starttag(self, tag, attrs):
        a = dict((k, v if v is not None else "") for k, v in attrs)
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "table":
            self._stack.append({"table": Table(), "cells": None, "cell": None})
        elif tag == "tr" and self._stack:
            ctx = self._stack[-1]
            self._close_row(ctx)
            ctx["cells"] = []
        elif tag in ("td", "th") and self._stack:
            ctx = self._stack[-1]
            self._close_cell(ctx)
            if ctx["cells"] is None:
                ctx["cells"] = []
            span = a.get("colspan", "1").strip()
            ctx["cell"] = {"th": tag == "th", "text": [], "hrefs": [],
                           "span": int(span) if span.isdigit() and 0 < int(span) < 50 else 1}
        elif tag == "br" and self._stack and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"]["text"].append(" ")
        elif tag == "a" and "href" in a:
            self._anchor = [a["href"], []]
            if self._stack and self._stack[-1]["cell"] is not None:
                self._stack[-1]["cell"]["hrefs"].append(a["href"])
        elif tag == "form":
            self._form = {"name": a.get("name", ""), "id": a.get("id", ""),
                          "action": a.get("action", ""), "method": a.get("method", ""), "inputs": []}
            self.page.forms.append(self._form)
        elif tag == "input" and self._form is not None:
            self._form["inputs"].append({"name": a.get("name", ""), "type": a.get("type", "text").lower(),
                                         "value": a.get("value", "")})

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "table" and self._stack:
            ctx = self._stack.pop()
            self._close_row(ctx)
            self.page.tables.append(ctx["table"])
        elif tag == "tr" and self._stack:
            self._close_row(self._stack[-1])
        elif tag in ("td", "th") and self._stack:
            self._close_cell(self._stack[-1])
        elif tag == "a" and self._anchor is not None:
            self.page.links.append((self._anchor[0], _text(self._anchor[1])))
            self._anchor = None
        elif tag == "form":
            self._form = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._anchor is not None:
            self._anchor[1].append(data)
        if self._stack and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"]["text"].append(data)

    def finish(self):
        self.close()
        while self._stack:
            ctx = self._stack.pop()
            self._close_row(ctx)
            self.page.tables.append(ctx["table"])
        return self.page


def _parse(text):
    parser = _PageParser()
    parser.feed(text)
    return parser.finish()


def parse_page(text):
    """표·링크·양식을 한 번에 읽는다."""
    return _parse(text)


def parse_tables(text):
    """표 목록: 각 표는 .headers(th 글자)와 .rows(Row: .cells, .hrefs)를 가진다."""
    return _parse(text).tables


def _has_login_form(page):
    for form in page.forms:
        for item in form["inputs"]:
            if item["type"] == "password" or item["name"] == "pass":
                return True
    return False


# ---------------------------------------------------------------------------
# 로그인과 수집
# ---------------------------------------------------------------------------

CollectResult = collections.namedtuple(
    "CollectResult", ["payments", "projects", "payment_pages", "project_pages", "login_info",
                      "project_skipped", "diag"], defaults=(0, None))


def login(opener, user_id, password):
    """로그인 양식을 읽어 id·pass와 숨은 입력을 POST한다. 리디렉션은 따라가지 않는다(P-7).

    ID·비밀번호는 이 함수의 인자와 POST 본문에만 있다.
    """
    status, _, text = opener.get(BASE + "/")
    page = _parse(text)
    form = None
    for candidate in page.forms:
        if candidate["name"] == "form1" or candidate["id"] == "form1":
            form = candidate
            break
    if form is None:
        raise StructureMismatch("로그인 화면에서 form1 양식을 찾지 못함")
    names = [item["name"] for item in form["inputs"]]
    if "id" not in names or "pass" not in names:
        raise StructureMismatch("로그인 양식에 id 또는 pass 입력이 없음")
    action = urllib.parse.urljoin(BASE + "/", form["action"]).split("#", 1)[0]
    if action != BASE + "/login/submit":
        raise StructureMismatch("로그인 양식의 전송 위치가 예상(/login/submit)과 다름")
    fields = [(item["name"], item["value"]) for item in form["inputs"]
              if item["type"] == "hidden" and item["name"] and item["name"] not in ("id", "pass")]
    fields.append(("id", user_id))
    fields.append(("pass", password))
    code, redirect_path, _ = opener.post(BASE + "/login/submit", fields, follow=False)
    return {"status": code, "redirect_path": redirect_path}


def _key(text):
    return _SPACE.sub("", text)


def _compare_header(headers, expected, aliases):
    """(일치 여부, 없는 이름, 새로 생긴 이름, 첫 차이 설명)"""
    want = [_key(x) for x in expected]
    got = [_key(x) for x in headers]
    alias_of = {}
    for pos, names in aliases.items():
        for name in names:
            alias_of[_key(name)] = want[pos]
    got_folded = [alias_of.get(x, x) for x in got]
    ok = len(got) == len(want)
    first = ""
    for i in range(max(len(got), len(want))):
        a = want[i] if i < len(want) else None
        b = got_folded[i] if i < len(got_folded) else None
        if a != b:
            ok = False
            first = "%d번째 칸: 예상 '%s', 실제 '%s'" % (
                i + 1, expected[i] if i < len(expected) else "(없음)",
                headers[i] if i < len(headers) else "(없음)")
            break
    missing = collections.Counter(x for x in want if x)
    missing.subtract(collections.Counter(x for x in got_folded if x))
    names = {}
    for raw in expected:
        names[_key(raw)] = raw
    miss = [names[k] for k, n in missing.items() if n > 0 for _ in range(n)]
    extra_counter = collections.Counter(x for x in got_folded if x)
    extra_counter.subtract(collections.Counter(x for x in want if x))
    shown = {}
    for raw in headers:
        shown[_key(raw)] = raw
    extra = [shown.get(k, k) for k, n in extra_counter.items() if n > 0 for _ in range(n)]
    return ok, miss, extra, first


def _is_total(cells):
    return any(c.strip().lower() in TOTAL_WORDS for c in cells[:2])


def _pro_num(row):
    for hrefs in row.hrefs:
        for href in hrefs:
            parts = urllib.parse.urlsplit(href)
            m = re.match(r"^pro_num=([0-9]+)$", parts.query)
            if parts.path == "/project/payment" and m:
                return m.group(1)
    return ""


def _map_payment(row):
    # 주민번호 모양 값은 읽는 곳에서 가린다: 스냅숏 CSV·화면·stdout 어디에도 나가지 않는다 (D-36, CR-02)
    return dict(zip(PAYMENT_KEYS, [mask_rrn(c) for c in row.cells[:len(PAYMENT_KEYS)]]))


def _map_project(row):
    cells = [mask_rrn(c) for c in row.cells]  # D-36, CR-02
    values = cells[1:15] + cells[16:20]
    mapped = dict(zip(PROJECT_KEYS[:-1], values))
    mapped["pro_num"] = _pro_num(row)
    return mapped


_LISTS = {
    "payment": {"label": "지급요청", "path": "/payment/index", "header": PAYMENT_HEADER,
                "aliases": PAYMENT_ALIASES, "mapper": _map_payment},
    "project": {"label": "프로젝트", "path": "/project/index", "header": PROJECT_HEADER,
                "aliases": PROJECT_ALIASES, "mapper": _map_project, "skip_bad": True},
}


def _match_table(page, spec):
    """머리글이 가장 맞는 표를 찾는다: (표 또는 None, 일치 여부, 없는 이름, 새로 생긴 이름, 첫 차이)."""
    best = None
    best_score = 0
    wanted = set(_key(x) for x in spec["header"] if x)
    for table in page.tables:
        if not table.headers:
            continue
        ok, miss, extra, first = _compare_header(table.headers, spec["header"], spec["aliases"])
        if ok:
            return table, True, [], [], ""
        score = len(wanted & set(_key(x) for x in table.headers))
        if score > best_score:
            best, best_score = (table, miss, extra, first), score
    if best is None or best_score < 2:
        return None, False, [], [], ""
    return best[0], False, best[1], best[2], best[3]


def _find_table(page, spec):
    """머리글이 맞는 표를 찾는다. 없으면 가장 비슷한 표의 차이를 알리며 멈춘다."""
    label = spec["label"]
    table, ok, miss, extra, first = _match_table(page, spec)
    if ok:
        return table
    if table is None:
        raise StructureMismatch("%s 목록 머리글 표를 찾지 못함 (화면 구조가 달라졌을 수 있음)" % label)
    raise StructureMismatch("%s 목록 머리글이 예상과 다름 — 없음: %s / 새로 생김: %s / 첫 차이 %s" % (
        label, ", ".join(miss) or "(없음)", ", ".join(extra) or "(없음)", first or "(칸 수 차이)"))


def _expand_spans(row):
    """colspan 칸을 빈 칸으로 펼친 줄 (칸 수 = 화면의 열 수). 펼칠 것이 없으면 그대로."""
    if all(n == 1 for n in row.spans):
        return row
    cells, hrefs = [], []
    for c, h, n in zip(row.cells, row.hrefs, row.spans):
        cells.append(c)
        hrefs.append(h)
        cells.extend([""] * (n - 1))
        hrefs.extend([[] for _ in range(n - 1)])
    return Row(cells, hrefs)


def _row_shape(i, row):
    """칸 수가 다른 줄의 모양 (값은 담지 않는다: 칸 수, colspan, 빈 칸 위치, 번호 칸이 숫자인지)."""
    spans = [(k, n) for k, n in enumerate(row.spans) if n != 1]
    empty = [k for k, c in enumerate(row.cells) if not c.strip()]
    numeric = [k for k, c in enumerate(row.cells[:3]) if _DIGITS.match(c.strip()) and c.strip()]
    return "줄 %d: %d칸, colspan %s, 빈 칸 %s, 앞 3칸 중 숫자 칸 %s, 링크 칸 %s" % (
        i + 1, len(row.cells), spans or "없음", empty, numeric,
        [k for k, h in enumerate(row.hrefs) if h])


def _split_rows(table, spec, shapes=None):
    """표의 데이터 줄을 키가 붙은 dict로, 칸 수가 다른 줄 수와 함께: (줄 목록, 칸 수가 다른 줄 수).
    Total 줄·빈 줄·안내 한 칸 줄은 데이터가 아니다. colspan 은 빈 칸으로 펼친 뒤 센다.
    shapes 목록을 주면 칸 수가 다른 줄의 모양(값 없이)을 담는다."""
    width = len(spec["header"])
    rows = []
    bad = 0
    for i, row in enumerate(table.rows):
        cells = row.cells
        if _is_total(cells) or not any(cells) or len(cells) == 1:
            continue
        full = _expand_spans(row)
        if len(full.cells) != width and not any(row.hrefs) and not any(
                _DIGITS.match(c.strip()) and c.strip() for c in row.cells[:3]):
            # 번호도 링크도 없는 줄 (실제 프로젝트 목록 2026-11-04: 칸을 합친 안내·묶음 줄): 데이터가 아니다
            if shapes is not None:
                shapes.append(_row_shape(i, row) + " → 데이터 줄 아님 (번호·링크 없음)")
            continue
        if len(full.cells) != width:
            bad += 1
            if shapes is not None:
                shapes.append(_row_shape(i, row))
            continue
        rows.append(spec["mapper"](full))
    return rows, bad


def _read_rows(table, spec, shapes=None):
    """지급요청은 칸 수가 다른 줄이 있으면 멈춘다 (승인 자료를 빠뜨리지 않는다).
    프로젝트 목록은 그 줄만 건너뛰고 (줄 목록, 건너뛴 수)로 알린다: 계산서 연결에만 쓰여 한 줄이 빠져도 미연결로 드러난다."""
    rows, bad = _split_rows(table, spec, shapes)
    if bad and not spec.get("skip_bad"):
        raise StructureMismatch("%s 목록 표 줄의 칸 수가 머리글과 다름 (%d건, 머리글 %d칸)" % (
            spec["label"], bad, len(spec["header"])))
    return rows, bad


def _pairs(query):
    """'a=1&b=' → [('a','1'), ('b','')] (이름순서 그대로, 빈 항목은 건너뜀)"""
    out = []
    for item in query.split("&"):
        if item:
            name, _, value = item.partition("=")
            out.append((name, value))
    return out


def _significant(pairs):
    """값이 빈 항목은 없는 것과 같다."""
    return set((n, v) for n, v in pairs if v != "")


def _is_first_page_pair(name, value):
    if value == "":
        return True
    if not _DIGITS.match(value):
        return False
    if name in _PAGE_NAMES_ONE_BASED:
        return int(value) <= 1
    if name in _PAGE_NAMES_ZERO_BASED:
        return int(value) == 0
    return False


def _canonical(url):
    """같은 쪽을 가리키는 주소를 같은 값으로 (page=1, 쪽 이름 없음, 끝 /0)."""
    parts = urllib.parse.urlsplit(url)
    path = re.sub(r"/0+$", "", parts.path.rstrip("/"))
    pairs = sorted((n, v) for n, v in _pairs(parts.query) if v != "" and not _is_first_page_pair(n, v))
    return path, tuple(pairs)


def _classify_links(page, current_url, kind, list_path):
    """쪽 이동 링크를 가려낸다.

    (따라갈 주소들, 알아본 쪽 링크 수, 알 수 없는 쪽 이름, 다른 조회값을 섞은 이름, 링크 모양 정보)
    링크 모양 정보: {'query': {쪽 이름: 개수}, 'path_number': 경로 숫자 링크 수, 'max_number': 가장 큰 번호 또는 None,
    'unfollowed': 따라가지 않을 같은 목록 링크의 조회 이름}
    """
    cur = urllib.parse.urlsplit(current_url)
    cur_set = _significant(_pairs(cur.query))
    known = FILTER_NAMES[kind] | PAGE_NAMES
    follow = []
    recognised = 0
    unknown = set()
    mixed = set()
    shape = {"query": {}, "path_number": 0, "max_number": None, "unfollowed": set()}
    for href, _text in page.links:
        h = href.strip()
        if not h or h.startswith("#") or h.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        try:
            full = urllib.parse.urljoin(current_url, h).split("#", 1)[0]
            parts = urllib.parse.urlsplit(full)
            host = parts.hostname
            parts.port
        except ValueError:
            continue
        if parts.scheme != "https" or host != HOST:
            continue
        if not re.match(r"^%s(?:/[0-9]+)?/?$" % re.escape(list_path), parts.path):
            continue
        link_set = _significant(_pairs(parts.query))
        diff = link_set ^ cur_set
        if not diff and parts.path == cur.path:
            continue  # 지금 보는 쪽
        names = set(n for n, _ in diff)
        if names <= PAGE_NAMES and all(_DIGITS.match(v) for _, v in diff):
            recognised += 1
            numbers = [int(v) for _, v in diff if v]
            if diff:
                for n in names:
                    shape["query"][n] = shape["query"].get(n, 0) + 1
            else:
                shape["path_number"] += 1
                tail = re.search(r"/([0-9]+)$", parts.path)
                if tail:
                    numbers.append(int(tail.group(1)))
            if numbers and (shape["max_number"] is None or max(numbers) > shape["max_number"]):
                shape["max_number"] = max(numbers)
            try:
                follow.append(check_url("GET", full))
            except BlockedRequest as e:
                # 알아본 쪽 링크를 조용히 버리면 1쪽만 읽고 '완료'가 된다 (실제 인트라넷 2026-11-04) → 멈춘다
                raise StructureMismatch("쪽 이동 링크를 읽을 수 없어 멈춤 — %s" % e)
            continue
        added = set((n, v) for n, v in link_set - cur_set)
        # 쪽 링크가 지금 주소에 없던 조회 값만 더 붙인 경우 (실제 인트라넷 2026-11-04: page 링크에 gyear=2026).
        # 바로 따라가지 않고 후보로만 남긴다 → _collect_list 가 그 값을 붙인 첫 쪽이 지금 첫 쪽과 같은지 확인한 뒤 다시 읽는다.
        cur_names = set(n for n, _ in cur_set)
        removed = set(n for n, _ in cur_set - link_set)
        extra = [(n, v) for n, v in added if n not in PAGE_NAMES]
        if (any(n in PAGE_NAMES and v.isdigit() for n, v in added) and extra and removed <= PAGE_NAMES
                and all(n in FILTER_NAMES[kind] and n not in cur_names for n, _ in extra)):
            shape.setdefault("adopt", set()).update(extra)
        shape["unfollowed"].update(n for n, v in added if n not in PAGE_NAMES)
        unknown.update(n for n, v in added if n not in known and v.isdigit())
        if any(n in PAGE_NAMES and v.isdigit() for n, v in added):
            mixed.update(n for n, v in added if n not in PAGE_NAMES)
    return follow, recognised, unknown, mixed, shape


def _mask_link(url):
    """구조 점검용 링크 모양: 경로 + 조회 이름 (숫자 값만 보이고 나머지 값은 *)."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "(읽을 수 없는 주소)"
    q = "&".join("%s=%s" % (n, v if _DIGITS.match(v) else "*") for n, v in _pairs(parts.query))
    return parts.path + ("?" + q if q else "")


def _list_links(page, current_url, list_path):
    out = []
    for href, _t in page.links:
        h = href.strip()
        if not h or h.startswith("#") or h.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        try:
            full = urllib.parse.urljoin(current_url, h)
            path = urllib.parse.urlsplit(full).path
        except ValueError:
            continue
        if path.startswith(list_path):
            out.append(_mask_link(full))
    return out


def _collect_list(opener, kind, max_pages, progress, adopt=None, expect=None, diag=None):
    """adopt: 첫 쪽 주소에 붙일 조회 값 (쪽 링크가 붙여 온 것), expect: 그때 첫 쪽에서 읽어야 하는 줄 (같은 목록인지 확인).
    diag 목록을 주면 쪽마다 구조(줄 수, 칸 수가 다른 줄 모양, 같은 목록 링크 모양)를 값 없이 담는다.
    -> (줄 목록, 쪽 수, 건너뛴 줄 수)"""
    if diag is None:
        diag = []
    skipped = 0
    spec = _LISTS[kind]
    label = spec["label"]
    list_path = spec["path"]
    start = BASE + list_path
    if adopt:
        start = check_url("GET", start + "?" + "&".join("%s=%s" % (n, urllib.parse.quote(v, safe="")) for n, v in sorted(adopt)))
    queue = [start]
    seen = set([_canonical(start)])
    linked, fetched = set(), set()   # 쪽 링크로 본 주소 · 실제로 읽은 주소 (끝에 다 읽었는지 맞춰 본다)
    rows = collections.OrderedDict()
    pages = 0
    while queue:
        if pages >= max_pages:
            raise StructureMismatch(
                "%s 목록: 최대 페이지 수 %d 도달 — 남은 페이지가 있어 수집을 멈춤 (--최대페이지로 늘릴 수 있음)"
                % (label, max_pages))
        url = queue.pop(0)
        fetched.add(_canonical(url))
        _, _, text = opener.get(url)
        pages += 1
        page = _parse(text)
        if _has_login_form(page):
            raise LoginFailed("로그인 실패: ID 또는 비밀번호를 확인하세요")
        table = _find_table(page, spec)
        shapes = []
        diag.append("%s %s: 표 줄 %d개, 머리글 %d칸" % (label, _mask_link(url), len(table.rows), len(table.headers)))
        added = 0
        empty_number = 0
        clashes = []
        try:
            mapped_rows, bad = _read_rows(table, spec, shapes)
        finally:
            diag.extend("  " + x for x in shapes)
        skipped += bad
        for mapped in mapped_rows:
            number = mapped["번호"].strip()
            if not number:
                empty_number += 1
            elif number not in rows:
                rows[number] = mapped
                added += 1
            elif rows[number] != mapped:
                clashes.append(number)  # 같은 번호의 다른 줄: 조용히 버리지 않는다 (WR-07). 같은 줄을 다시 읽은 것은 괜찮다
        if empty_number:
            raise StructureMismatch("%s 목록: 번호 칸이 빈 줄이 %d건 있어 멈춤" % (label, empty_number))
        if clashes:
            raise StructureMismatch("%s 목록: 번호가 같은데 내용이 다른 줄 %d건 (%s) — 번호로 요청을 구별할 수 없어 멈춤"
                                    % (label, len(clashes), ", ".join(sorted(set(clashes))[:5])))
        if progress is not None:
            progress(label, pages, len(rows))
        if pages == 1 and expect is not None and list(rows.values()) != expect:
            raise StructureMismatch("%s 목록: 쪽 링크의 조회 값(%s)을 붙이면 첫 쪽 내용이 달라져 멈춤"
                                    % (label, ", ".join(sorted(n for n, _ in adopt or ()))))
        follow, recognised, unknown, mixed, shape = _classify_links(page, url, kind, list_path)
        links = _list_links(page, url, list_path)
        diag.append("  같은 목록 링크 %d개: %s" % (len(links), ", ".join(sorted(set(links))[:40])))
        diag.append("  쪽 링크로 알아봄 %d · 따라갈 주소 %d · 알 수 없는 이름 %s · 함께 바뀌는 조회 %s" % (
            recognised, len(follow), sorted(unknown), sorted(mixed)))
        if pages == 1 and not recognised:
            pairs = shape.get("adopt") or set()
            names = [n for n, _ in pairs]
            if mixed and not unknown and adopt is None and pairs and len(names) == len(set(names)) and set(names) == mixed:
                # 같은 이름에 값이 하나뿐일 때만: 그 값을 붙여 첫 쪽부터 다시 읽고 첫 쪽이 같아야 이어 간다
                diag.append("  → 쪽 링크의 조회 값 %s 을 붙여 첫 쪽부터 다시 읽음" % sorted(n for n, _ in pairs))
                return _collect_list(opener, kind, max_pages, progress, adopt=pairs, expect=list(rows.values()), diag=diag)
            if unknown:
                raise StructureMismatch(
                    "%s 목록: 쪽 이동으로 보이는 링크의 조회 이름(%s)을 알 수 없어 따라가지 않고 멈춤"
                    % (label, ", ".join(sorted(unknown))))
            if mixed:
                raise StructureMismatch(
                    "%s 목록: 쪽 링크가 다른 조회 값(%s)도 함께 바꿔서 따라가지 않고 멈춤"
                    % (label, ", ".join(sorted(mixed))))
        linked.update(_canonical(link) for link in follow)
        if added:  # 새 줄이 없는 쪽의 링크는 따라가지 않는다(되돌이 방지)
            for link in follow:
                key = _canonical(link)
                if key not in seen:
                    seen.add(key)
                    queue.append(link)
    if not rows:
        raise StructureMismatch("%s 목록 0건 — 읽은 줄이 없어 멈춤" % label)
    missing = linked - fetched
    diag.append("  %s 목록: 읽은 쪽 %d · 링크로 본 쪽 중 안 읽은 쪽 %d · 줄 %d건" % (label, pages, len(missing), len(rows)))
    if missing:
        raise StructureMismatch("%s 목록: 쪽 링크로 보인 쪽 %d개를 읽지 못해 멈춤 (일부만 읽은 자료는 저장하지 않음)"
                                % (label, len(missing)))
    return list(rows.values()), pages, skipped


def collect(opener, user_id, password, max_pages=300, progress=None, diag=None):
    """로그인 → 지급요청 목록 전 페이지 → 프로젝트 목록 전 페이지.

    구조가 예상과 다르면 예외로 멈추고 아무 줄도 돌려주지 않는다(D-29).
    ID·비밀번호는 login()에만 넘기고 어디에도 보관하지 않는다.
    """
    if diag is None:
        diag = []
    info = login(opener, user_id, password)
    payments, payment_pages, _ = _collect_list(opener, "payment", max_pages, progress, diag=diag)
    projects, project_pages, skipped = _collect_list(opener, "project", max_pages, progress, diag=diag)
    return CollectResult(payments, projects, payment_pages, project_pages, info, skipped, diag)


def _paging_stop(label, recognised, unknown, mixed):
    """collect가 첫 쪽에서 쪽 이동을 알아보지 못해 멈출 때의 이유(아니면 빈 글)."""
    if recognised:
        return ""
    if unknown:
        return "%s 목록: 쪽 이동으로 보이는 링크의 조회 이름(%s)을 알 수 없음" % (label, ", ".join(sorted(unknown)))
    if mixed:
        return "%s 목록: 쪽 링크가 다른 조회 값(%s)도 함께 바꿈" % (label, ", ".join(sorted(mixed)))
    return ""


def _survey_list(opener, kind):
    """목록의 첫 쪽만 읽어 구조를 요약한다. 멈추지 않고 차이를 알린다(로그인 양식·막힌 요청은 예외)."""
    spec = _LISTS[kind]
    label = spec["label"]
    url = BASE + spec["path"]
    _, _, text = opener.get(url)
    page = _parse(text)
    if _has_login_form(page):
        raise LoginFailed("로그인 실패: ID 또는 비밀번호를 확인하세요")
    table, ok, miss, extra, first = _match_table(page, spec)
    rows, bad, total_row = [], 0, False
    if table is not None:
        rows, bad = _split_rows(table, spec)
        total_row = any(_is_total(r.cells) for r in table.rows)
    _, recognised, unknown, mixed, shape = _classify_links(page, url, kind, spec["path"])
    stop = _paging_stop(label, recognised, unknown, mixed)
    return {
        "table_found": table is not None,
        "header_ok": ok,
        "missing": miss,
        "extra": extra,
        "first_difference": first,
        "rows": len(rows),
        "bad_rows": bad,
        "total_row": total_row,
        "pro_num_links": sum(1 for r in rows if r.get("pro_num")),
        "page_links": {"query": shape["query"], "path_number": shape["path_number"],
                       "max_number": shape["max_number"]},
        "unfollowed_query_names": sorted(shape["unfollowed"]),
        "paging_stop": stop,
        "rows_data": rows,
    }


def structure_report(opener, user_id, password):
    """구조 점검: 로그인 → 두 목록의 첫 쪽만 읽어 머리글·줄 수·쪽 링크 모양을 요약한다. 쪽 이동은 따라가지 않는다.

    LoginFailed·BlockedRequest는 그대로 낸다. 보고서에는 ID·비밀번호가 들어가지 않는다.
    """
    info = login(opener, user_id, password)
    report = {"login": info}
    for kind in ("payment", "project"):
        report[kind] = _survey_list(opener, kind)
    report["ok"] = all(report[k]["header_ok"] and report[k]["rows"] > 0 and report[k]["bad_rows"] == 0
                       and not report[k]["paging_stop"] for k in ("payment", "project"))
    return report
