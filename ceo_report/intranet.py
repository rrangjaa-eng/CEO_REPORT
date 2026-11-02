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

HOST = "intranet.plant8.co.kr"
BASE = "https://" + HOST
USER_AGENT = "Mozilla/5.0 (compatible; CEO_REPORT read-only collector)"

# 스냅숏 열과 같아야 한다(계획 01.1-03에서 snapshot 모듈의 목록을 가져다 쓰도록 바꾼다)
PAYMENT_KEYS = ["번호", "행사명", "파트너", "등록일", "행사일", "금액", "지급요청일", "등록자",
                "팀장승인", "관리팀승인", "사장님승인"]
PROJECT_KEYS = ["번호", "클라이언트", "담당자", "PO번호", "행사일", "행사명", "국", "팀", "등록자",
                "계산서", "사전견적", "견적금액", "실행가", "수익률",
                "승인_담당자", "승인_팀장", "승인_관리팀", "승인_대표이사", "pro_num"]

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
_BAD_VALUE_FRAGMENTS = ("/confirm", "/logout", "://", "javascript:", "<", ">")
_LIST_RE = re.compile(r"^/(payment|project)/index(?:/([0-9]+))?$")
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
        try:
            return self._fetch(req)
        except urllib.error.HTTPError as exc:
            if follow or not 300 <= exc.code < 400:
                raise
            location = exc.headers.get("Location") if exc.headers is not None else None
            exc.close()
            path = urllib.parse.urlsplit(location).path if location else None
            return exc.code, path or None, ""


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
        urllib.request.ProxyHandler(proxies),
        transport,
        urllib.request.HTTPCookieProcessor(jar),
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

    def __init__(self, cells, hrefs):
        self.cells = cells
        self.hrefs = hrefs


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
                                             [list(c["hrefs"]) for c in cells]))
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
            ctx["cell"] = {"th": tag == "th", "text": [], "hrefs": []}
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
    "CollectResult", ["payments", "projects", "payment_pages", "project_pages", "login_info"])


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


def _headers_match(headers, expected, aliases):
    if len(headers) != len(expected):
        return False
    for i, (got, want) in enumerate(zip(headers, expected)):
        ok = [_key(want)] + [_key(x) for x in aliases.get(i, ())]
        if _key(got) not in ok:
            return False
    return True


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
    return dict(zip(PAYMENT_KEYS, row.cells[:len(PAYMENT_KEYS)]))


def _map_project(row):
    cells = row.cells
    values = cells[1:15] + cells[16:20]
    mapped = dict(zip(PROJECT_KEYS[:-1], values))
    mapped["pro_num"] = _pro_num(row)
    return mapped


def _read_list(opener, path, header, aliases, mapper):
    _, _, text = opener.get(BASE + path)
    page = _parse(text)
    if _has_login_form(page):
        raise LoginFailed("로그인 실패: ID 또는 비밀번호를 확인하세요")
    for table in page.tables:
        if _headers_match(table.headers, header, aliases):
            return [mapper(r) for r in table.rows if not _is_total(r.cells)]
    raise StructureMismatch("목록 머리글이 예상과 다름")


def collect(opener, user_id, password, max_pages=300, progress=None):
    """로그인 → 지급요청 목록 → 프로젝트 목록. (이 단계: 목록마다 한 쪽만 읽는다)"""
    info = login(opener, user_id, password)
    payments = _read_list(opener, "/payment/index", PAYMENT_HEADER, PAYMENT_ALIASES, _map_payment)
    projects = _read_list(opener, "/project/index", PROJECT_HEADER, PROJECT_ALIASES, _map_project)
    return CollectResult(payments, projects, 1, 1, info)
