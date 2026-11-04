"""인트라넷 수집기 테스트. 네트워크는 쓰지 않는다(가짜 transport + 가짜 HTML).

실행: python -m unittest discover -s tests
다른 테스트 파일은 이 파일에서 함수와 클래스(FakeTransport, login_page, payment_page,
project_page)만 가져다 쓴다. TestCase 클래스는 가져가지 않는다.
"""
import builtins
import http.client
import http.cookiejar
import io
import os
import shutil
import ssl
import subprocess
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from html import escape
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE = "https://intranet.plant8.co.kr"
USER = "가상아이디-7c1"
PASSWORD = "S3ntinel-Pw!9f2c"
PASSWORD_ENC = "S3ntinel-Pw%219f2c"

# 계약(01.1-02 PLAN Interface contract)의 글자 그대로 — 구현과 따로 적어 둔 기대값
PAYMENT_KEYS = ["번호", "행사명", "파트너", "등록일", "행사일", "금액", "지급요청일", "등록자",
                "팀장승인", "관리팀승인", "사장님승인"]
PROJECT_KEYS = ["번호", "클라이언트", "담당자", "PO번호", "행사일", "행사명", "국", "팀", "등록자",
                "계산서", "사전견적", "견적금액", "실행가", "수익률",
                "승인_담당자", "승인_팀장", "승인_관리팀", "승인_대표이사", "pro_num"]
PAYMENT_HEADER = PAYMENT_KEYS + ["삭제"]
PROJECT_HEADER = ["", "번호", "클라이언트", "담당자", "PO번호", "행사일", "행사명", "국", "팀", "등록자",
                  "계산서", "사전견적", "견적금액", "실행가", "수익률", "", "담당자", "팀장", "관리팀",
                  "대표이사", "견적", "삭제"]


def intranet():
    """모듈은 테스트 안에서 가져온다 — 모듈이 없을 때 파일 전체가 아니라 해당 테스트만 실패한다."""
    from ceo_report import intranet as module
    return module


# ---------------------------------------------------------------------------
# 가짜 사이트 (모든 글자는 가상 자료)
# ---------------------------------------------------------------------------

class FakeTransport(urllib.request.BaseHandler):
    """https 열기를 대신하는 urllib 처리기. 실제 소켓을 쓰지 않고 요청을 기록한다.

    routes: {(방식, '경로?쿼리'): (상태코드, {머리글}, 본문)} 또는 예외 객체(그대로 던진다).
    없는 경로는 404.
    """

    def __init__(self, routes):
        self.routes = dict(routes)
        self.calls = []  # (방식, 전체 주소, 본문 bytes, Cookie 머리글)

    def https_open(self, req):
        method = req.get_method()
        self.calls.append((method, req.full_url, req.data, req.get_header("Cookie")))
        parts = urllib.parse.urlsplit(req.full_url)
        key = (method, parts.path + ("?" + parts.query if parts.query else ""))
        route = self.routes.get(key)
        if isinstance(route, BaseException):
            raise route
        if route is None:
            route = (404, {}, "")
        status, headers, body = route
        lines = []
        merged = {"Content-Type": "text/html; charset=utf-8"}
        merged.update(headers)
        for name, value in merged.items():
            for one in (value if isinstance(value, (list, tuple)) else [value]):
                lines.append("%s: %s\r\n" % (name, one))
        raw = ("".join(lines) + "\r\n").encode("iso-8859-1")
        resp = urllib.response.addinfourl(io.BytesIO(body.encode("utf-8")),
                                          http.client.parse_headers(io.BytesIO(raw)),
                                          req.full_url, status)
        resp.msg = "가상"
        return resp

    def paths(self):
        """[(방식, 경로)] — 쿼리 없이."""
        return [(m, urllib.parse.urlsplit(u).path) for m, u, _, _ in self.calls]

    def requested(self):
        """[(방식, 경로?쿼리)]"""
        out = []
        for m, u, _, _ in self.calls:
            p = urllib.parse.urlsplit(u)
            out.append((m, p.path + ("?" + p.query if p.query else "")))
        return out


def _page(body):
    return ("<html><head><meta charset='utf-8'><title>가상 인트라넷</title></head><body>%s</body></html>"
            % body)


def login_page(hidden=None, form_name="form1"):
    hidden = {"_token": "tok-123"} if hidden is None else hidden
    inputs = "".join("<input type='hidden' name='%s' value='%s'>" % (escape(k), escape(v))
                     for k, v in hidden.items())
    return _page("<form name='%s' id='%s' method='post' action='/login/submit'>%s"
                 "<input type='text' name='id'><input type='password' name='pass'>"
                 "<button type='submit'>로그인</button></form>" % (form_name, form_name, inputs))


_NAV = ("<table class='layout'><tr><td><a href='/payment/index'>가상 지급요청</a></td>"
        "<td><a href='/project/index'>가상 프로젝트</a></td>"
        "<td><a href='/logout'>로그아웃</a></td><td><a href='/project/logout'>나가기</a></td></tr></table>")
_SEARCH = ("<form method='get' action='/payment/index'><input type='text' name='search'>"
           "<select name='confirm'><option value=''>승인구분</option></select></form>")


def _paging(links):
    if not links:
        return ""
    return "<div class='paging'>%s</div>" % "".join(
        "<a href='%s'>%s</a> " % (escape(h), escape(t)) for h, t in links)


def payment_page(rows, links=(), header=None):
    """rows: 줄마다 값 11개(PAYMENT_KEYS 순서). 삭제 칸은 만들어 붙인다. links: [(href, 글자)]."""
    header = PAYMENT_HEADER if header is None else header
    head = "".join("<th>%s</th>" % escape(h) for h in header)
    body = []
    for values in rows:
        n = values[0]
        cells = []
        for i, v in enumerate(values):
            if i == 1:
                cells.append("<td><a href='/payment/view/%s'>%s</a></td>" % (escape(n), escape(v)))
            elif i in (8, 9, 10):
                role = {8: "leader", 9: "mgmt", 10: "ceo"}[i]
                cells.append("<td><a href=\"javascript:checkconfirm('%s','/confirm/payment/%s/%s')\">%s</a></td>"
                             % (escape(n), escape(n), role, escape(v)))
            else:
                cells.append("<td>%s</td>" % escape(v))
        cells.append("<td><a href='/payment/delete/%s'>삭제</a></td>" % escape(n))
        body.append("<tr>%s</tr>" % "".join(cells))
    return _page("%s%s<table class='list'><thead><tr>%s</tr></thead><tbody>%s</tbody></table>%s"
                 % (_NAV, _SEARCH, head, "".join(body), _paging(links)))


def project_page(rows, links=(), header=None, total=True):
    """rows: 줄마다 값 19개(PROJECT_KEYS 순서, 마지막이 pro_num). 0번·15번 빈 칸과 견적·삭제 칸은 붙인다."""
    header = PROJECT_HEADER if header is None else header
    head = "".join("<th>%s</th>" % escape(h) for h in header)
    body = []
    if total:
        body.append("<tr><td colspan='6'>Total</td><td>가상 합계</td><td>1,000,000</td></tr>")
    for values in rows:
        pro_num = values[-1]
        data = list(values[:-1])
        cells = ["<td></td>"]
        for i, v in enumerate(data[:14]):
            if i == 5:
                cells.append("<td><a href='/project/payment?pro_num=%s'>%s</a></td>"
                             % (escape(pro_num), escape(v)))
            else:
                cells.append("<td>%s</td>" % escape(v))
        cells.append("<td></td>")
        for v in data[14:]:
            cells.append("<td>%s</td>" % escape(v))
        cells.append("<td><a href='/project/estimate/%s'>견적</a></td>" % escape(data[0]))
        cells.append("<td><a href='/project/delete/%s'>삭제</a></td>" % escape(data[0]))
        body.append("<tr>%s</tr>" % "".join(cells))
    return _page("%s<table class='list'><thead><tr>%s</tr></thead><tbody>%s</tbody></table>%s"
                 % (_NAV, head, "".join(body), _paging(links)))


def prow(n, name=None, amount="1,000,000", stages=("승인", "승인", "미승인")):
    return [str(n), name or "[26218] 가상행사 %s" % n, "가상파트너", "2026-10-30 09:10:11",
            "2026-11-20", amount, "2026-11-06", "가상기안자"] + list(stages)


def jrow(n, pro_num, name=None):
    return [str(n), "가상클라이언트", "가상담당", "PO-가상-%s" % n, "2026-11-20",
            name or "[%s] 가상프로젝트 %s" % (n, n), "가상국", "가상팀", "가상기안자", "발행",
            "50,000,000", "55,000,000", "40,000,000", "27.3%", "승인", "승인", "승인", "승인",
            str(pro_num)]


def site_routes(payment_rows=None, project_rows=None, extra=None):
    """로그인 → 지급요청 1쪽 → 프로젝트 1쪽으로 이어지는 기본 경로표."""
    if payment_rows is None:
        payment_rows = [prow(5101, amount="44,000,000"), prow(5102)]
    if project_rows is None:
        project_rows = [jrow(26218, 901)]
    routes = {
        ("GET", "/"): (200, {}, login_page()),
        ("POST", "/login/submit"): (302, {"Location": "/main", "Set-Cookie": "SESSID=s1; Path=/"}, ""),
        ("GET", "/payment/index"): (200, {}, payment_page(payment_rows)),
        ("GET", "/project/index"): (200, {}, project_page(project_rows)),
    }
    routes.update(extra or {})
    return routes


def make_fake_opener(routes=None, delay=0.3, sleep=None):
    fake = FakeTransport(site_routes() if routes is None else routes)
    opener = intranet().make_opener(transport=fake, proxies={}, delay=delay,
                                    sleep=(lambda s: None) if sleep is None else sleep)
    return opener, fake


# ---------------------------------------------------------------------------
# Task 1: 트레이서
# ---------------------------------------------------------------------------

class TestIntranetTracer(unittest.TestCase):
    def collect(self):
        opener, fake = make_fake_opener()
        result = intranet().collect(opener, USER, PASSWORD)
        return result, fake

    def test_rows_use_snapshot_column_layout(self):
        result, _ = self.collect()
        self.assertEqual(len(result.payments), 2)
        self.assertEqual(len(result.projects), 1)
        for row in result.payments:
            self.assertEqual(list(row.keys()), PAYMENT_KEYS)
        self.assertEqual(list(result.projects[0].keys()), PROJECT_KEYS)
        self.assertEqual(result.projects[0]["pro_num"], "901")
        self.assertEqual(result.projects[0]["번호"], "26218")
        first = result.payments[0]
        self.assertEqual(first["번호"], "5101")
        self.assertEqual(first["금액"], "44,000,000")
        self.assertEqual(first["사장님승인"], "미승인")  # 링크 글자이지 javascript 주소가 아니다
        self.assertEqual(result.payments[1]["번호"], "5102")

    def test_projects_skip_total_row_and_map_approval_columns(self):
        result, _ = self.collect()
        project = result.projects[0]
        self.assertEqual(project["수익률"], "27.3%")
        self.assertEqual(project["승인_담당자"], "승인")
        self.assertEqual(project["승인_대표이사"], "승인")
        self.assertEqual(project["행사명"], "[26218] 가상프로젝트 26218")

    def test_request_list_is_exactly_login_and_two_lists(self):
        _, fake = self.collect()
        self.assertEqual(fake.paths(), [("GET", "/"), ("POST", "/login/submit"),
                                        ("GET", "/payment/index"), ("GET", "/project/index")])

    def test_session_cookie_is_sent_after_login(self):
        _, fake = self.collect()
        self.assertIsNone(fake.calls[0][3])
        self.assertIn("SESSID=s1", fake.calls[2][3])
        self.assertIn("SESSID=s1", fake.calls[3][3])

    def test_post_body_holds_id_pass_and_hidden_token(self):
        _, fake = self.collect()
        fields = urllib.parse.parse_qs(fake.calls[1][2].decode("utf-8"))
        self.assertEqual(fields["id"], [USER])
        self.assertEqual(fields["pass"], [PASSWORD])
        self.assertEqual(fields["_token"], ["tok-123"])

    def test_login_info_has_status_and_redirect_path_only(self):
        result, _ = self.collect()
        self.assertEqual(result.login_info, {"status": 302, "redirect_path": "/main"})

    def test_key_lists_match_contract(self):
        module = intranet()
        self.assertEqual(list(module.PAYMENT_KEYS), PAYMENT_KEYS)
        self.assertEqual(list(module.PROJECT_KEYS), PROJECT_KEYS)
        self.assertEqual(module.HOST, "intranet.plant8.co.kr")
        self.assertEqual(module.BASE, BASE)


class TestCheckUrlBasics(unittest.TestCase):
    ALLOWED = [
        ("GET", BASE + "/"),
        ("POST", BASE + "/login/submit"),
        ("GET", BASE + "/payment/index"),
        ("GET", BASE + "/payment/index?page=2"),
        ("GET", BASE + "/project/index"),
        ("GET", BASE + "/project/payment?pro_num=903"),
    ]
    BLOCKED = [
        ("GET", BASE + "/confirm/payment/5101/ceo"),
        ("GET", BASE + "/logout"),
        ("GET", BASE + "/project/logout"),
        ("GET", BASE + "/payment/delete/5101"),
        ("GET", "http://intranet.plant8.co.kr/payment/index"),
        ("GET", "https://example.com/payment/index"),
    ]

    def test_allowed(self):
        check_url = intranet().check_url
        for method, url in self.ALLOWED:
            with self.subTest(method=method, url=url):
                self.assertEqual(check_url(method, url), url)

    def test_blocked(self):
        module = intranet()
        for method, url in self.BLOCKED:
            with self.subTest(method=method, url=url):
                with self.assertRaises(module.BlockedRequest):
                    module.check_url(method, url)


class TestSnapshotFolderIgnored(unittest.TestCase):
    SAMPLE_PATH = "수집/인트라넷_20261102_090000/지급요청.csv"

    def test_gitignore_has_snapshot_folder_line(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            lines = [line.strip() for line in f.read().splitlines()]
        self.assertIn("수집/", lines)
        self.assertIn("출력/", lines)  # 기존 줄은 그대로

    @unittest.skipUnless(shutil.which("git"), "git 없음")
    def test_git_check_ignore_matches_snapshot_path(self):
        r = subprocess.run(["git", "check-ignore", "-q", self.SAMPLE_PATH], cwd=ROOT)
        self.assertEqual(r.returncode, 0, "스냅숏 폴더가 git 제외 대상이 아님")


# ---------------------------------------------------------------------------
# Task 2: 허용 목록은 우회할 수 없다
# ---------------------------------------------------------------------------

class TestAllowlistMatrix(unittest.TestCase):
    BLOCKED = [
        # 이름으로 막는 것
        ("GET", BASE + "/confirm/payment/5101/ceo"),
        ("GET", BASE + "/payment/confirm/5101"),
        ("GET", BASE + "/logout"),
        ("GET", BASE + "/project/logout"),
        ("GET", BASE + "/payment/delete/5101"),
        ("GET", BASE + "/payment/del/5101"),
        ("GET", BASE + "/project/save"),
        ("GET", BASE + "/payment/update/1"),
        ("GET", BASE + "/payment/삭제/1"),
        # 방식이 틀린 것
        ("POST", BASE + "/payment/index"),
        ("GET", BASE + "/login/submit"),
        ("POST", BASE + "/"),
        # 주소 틀·호스트가 틀린 것
        ("GET", "http://intranet.plant8.co.kr/payment/index"),
        ("GET", "https://intranet.plant8.co.kr.evil.example/"),
        ("GET", "https://evil.example/payment/index"),
        ("GET", "https://user:pw@intranet.plant8.co.kr/"),
        ("GET", "https://intranet.plant8.co.kr:8443/"),
        # 경로 형식이 나쁜 것
        ("GET", BASE + "/payment/index/../confirm/1"),
        ("GET", BASE + "/payment/%2e%2e/confirm"),
        ("GET", BASE + "/payment//index"),
        ("GET", BASE + "/payment/index;del;"),
        # 조회 값이 나쁜 것
        ("GET", BASE + "/payment/index?del=1"),
        ("GET", BASE + "/payment/index?page=../../confirm"),
        ("GET", BASE + "/payment/index?page=2x"),
        ("GET", BASE + "/payment/index?search=javascript:alert(1)"),
        ("GET", BASE + "/project/payment?pro_num=1;drop"),
        ("GET", BASE + "/project/payment?pro_num=12&x=1"),
        ("GET", BASE + "/project/payment"),
        ("GET", BASE + "/project/index?confirm=1"),
        ("GET", BASE + "/?next=/payment/index"),
        # 그 밖
        ("GET", "javascript:checkconfirm('1','/confirm/payment/1/ceo')"),
        ("GET", BASE + "/payment/view/5101"),
    ]
    ALLOWED = [
        BASE + "/payment/index?gyear=2026&team=&subteam=&project=&partner=&writer=&search=&confirm=&page=3",
        BASE + "/payment/index/20",
        BASE + "/project/index?page=2",
        BASE + "/project/index/40",
        BASE + "/payment/index",
        BASE + "/project/payment?pro_num=903",
    ]

    def test_blocked_requests_never_reach_the_transport(self):
        module = intranet()
        for method, url in self.BLOCKED:
            with self.subTest(method=method, url=url):
                opener, fake = make_fake_opener()
                with self.assertRaises(module.BlockedRequest):
                    if method == "POST":
                        opener.post(url, [("a", "b")])
                    else:
                        opener.get(url)
                self.assertEqual(fake.calls, [])

    def test_check_url_blocks_the_same_matrix(self):
        module = intranet()
        for method, url in self.BLOCKED:
            with self.subTest(method=method, url=url):
                with self.assertRaises(module.BlockedRequest):
                    module.check_url(method, url)

    def test_allowed_urls_pass_unchanged(self):
        module = intranet()
        for url in self.ALLOWED:
            with self.subTest(url=url):
                self.assertEqual(module.check_url("GET", url), url)

    def test_fragment_is_stripped(self):
        module = intranet()
        self.assertEqual(module.check_url("GET", BASE + "/payment/index?page=2#top"),
                         BASE + "/payment/index?page=2")

    def test_block_message_has_method_and_path_but_no_query_values_or_userinfo(self):
        module = intranet()
        with self.assertRaises(module.BlockedRequest) as ctx:
            module.check_url("GET", BASE + "/payment/index?search=javascript:alert(1)")
        text = str(ctx.exception)
        self.assertIn("GET", text)
        self.assertIn("/payment/index", text)
        self.assertNotIn("alert", text)
        with self.assertRaises(module.BlockedRequest) as ctx:
            module.check_url("GET", "https://user:S3cret@intranet.plant8.co.kr/")
        self.assertNotIn("S3cret", str(ctx.exception))
        self.assertNotIn("S3cret", repr(ctx.exception))


class TestRedirectsChecked(unittest.TestCase):
    def test_redirect_to_confirm_is_blocked_before_it_is_sent(self):
        module = intranet()
        opener, fake = make_fake_opener(site_routes(extra={
            ("GET", "/payment/index"): (302, {"Location": "/confirm/payment/1"}, "")}))
        with self.assertRaises(module.BlockedRequest):
            opener.get(BASE + "/payment/index")
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse([c for c in fake.calls if "confirm" in c[1]])

    def test_redirect_to_other_host_is_blocked(self):
        module = intranet()
        opener, fake = make_fake_opener(site_routes(extra={
            ("GET", "/payment/index"): (302, {"Location": "https://evil.example/"}, "")}))
        with self.assertRaises(module.BlockedRequest):
            opener.get(BASE + "/payment/index")
        self.assertEqual(len(fake.calls), 1)

    def test_redirect_to_http_is_blocked(self):
        module = intranet()
        opener, fake = make_fake_opener(site_routes(extra={
            ("GET", "/payment/index"): (302, {"Location": "http://intranet.plant8.co.kr/payment/index"}, "")}))
        with self.assertRaises(module.BlockedRequest):
            opener.get(BASE + "/payment/index")
        self.assertEqual(len(fake.calls), 1)

    def test_redirect_to_allowed_target_is_followed(self):
        opener, fake = make_fake_opener(site_routes(extra={
            ("GET", "/payment/index"): (302, {"Location": "/payment/index?page=1"}, ""),
            ("GET", "/payment/index?page=1"): (200, {}, payment_page([prow(5101)]))}))
        status, final_url, text = opener.get(BASE + "/payment/index")
        self.assertEqual(status, 200)
        self.assertTrue(final_url.endswith("/payment/index?page=1"))
        self.assertIn("5101", text)
        self.assertEqual(fake.requested(), [("GET", "/payment/index"), ("GET", "/payment/index?page=1")])

    def test_redirect_to_login_page_then_collect_reports_login_failed(self):
        module = intranet()
        opener, fake = make_fake_opener(site_routes(extra={
            ("GET", "/payment/index"): (302, {"Location": "/"}, "")}))
        with self.assertRaises(module.LoginFailed):
            module.collect(opener, USER, PASSWORD)
        self.assertEqual(fake.paths()[-1], ("GET", "/"))

    def test_307_on_login_post_is_not_followed(self):
        opener, fake = make_fake_opener(site_routes(extra={
            ("POST", "/login/submit"): (307, {"Location": "/main"}, "")}))
        code, path, body = opener.post(BASE + "/login/submit", [("id", USER), ("pass", PASSWORD)])
        self.assertEqual((code, path, body), (307, "/main", ""))
        self.assertEqual(fake.paths(), [("POST", "/login/submit")])

    def test_login_redirect_target_is_never_requested(self):
        opener, fake = make_fake_opener(site_routes(extra={
            ("POST", "/login/submit"): (302, {"Location": "https://evil.example/steal"}, "")}))
        intranet().login(opener, USER, PASSWORD)
        self.assertEqual(fake.paths(), [("GET", "/"), ("POST", "/login/submit")])

    def test_redirect_loop_is_cut_off(self):
        opener, fake = make_fake_opener(site_routes(extra={
            ("GET", "/payment/index"): (302, {"Location": "/payment/index?page=1"}, ""),
            ("GET", "/payment/index?page=1"): (302, {"Location": "/payment/index"}, "")}))
        with self.assertRaises(urllib.error.HTTPError):
            opener.get(BASE + "/payment/index")
        self.assertLessEqual(len(fake.calls), 6)


class TestRequestGuard(unittest.TestCase):
    def test_inner_director_call_to_logout_is_blocked_and_not_sent(self):
        module = intranet()
        opener, fake = make_fake_opener()
        with self.assertRaises(module.BlockedRequest):
            opener.director.open(BASE + "/logout")
        self.assertEqual(fake.calls, [])

    def test_inner_director_call_with_request_object_and_post_body(self):
        module = intranet()
        opener, fake = make_fake_opener()
        with self.assertRaises(module.BlockedRequest):
            opener.director.open(urllib.request.Request(BASE + "/payment/index", data=b"x=1"))
        with self.assertRaises(module.BlockedRequest):
            opener.director.open(BASE + "/confirm/payment/1/ceo")
        self.assertEqual(fake.calls, [])

    def test_inner_director_http_scheme_fails_closed(self):
        module = intranet()
        opener, fake = make_fake_opener()
        with self.assertRaises(module.BlockedRequest):
            opener.director.open("http://intranet.plant8.co.kr/payment/index")
        self.assertEqual(fake.calls, [])


class TestTransportSafety(unittest.TestCase):
    PLAIN = ("http_open", "file_open", "ftp_open", "data_open")

    def handlers(self, **kwargs):
        return intranet().make_opener(**kwargs).director.handlers

    def test_no_plain_scheme_handlers_without_proxies(self):
        for handler in self.handlers(proxies={}):
            for attr in self.PLAIN:
                self.assertFalse(hasattr(handler, attr), "%s.%s" % (type(handler).__name__, attr))

    def test_with_system_proxy_settings_only_the_proxy_handler_may_differ(self):
        others = [h for h in self.handlers() if not isinstance(h, urllib.request.ProxyHandler)]
        for handler in others:
            for attr in self.PLAIN:
                self.assertFalse(hasattr(handler, attr), "%s.%s" % (type(handler).__name__, attr))
        self.assertEqual(len([h for h in others if hasattr(h, "https_open")]), 1)

    def test_one_https_handler_with_verification_on(self):
        https = [h for h in self.handlers(proxies={}) if hasattr(h, "https_open")]
        self.assertEqual(len(https), 1)
        context = https[0]._context
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_cookies_live_in_a_plain_in_memory_jar(self):
        procs = [h for h in self.handlers(proxies={}) if isinstance(h, urllib.request.HTTPCookieProcessor)]
        self.assertEqual(len(procs), 1)
        self.assertIs(type(procs[0].cookiejar), http.cookiejar.CookieJar)

    def test_opener_has_no_save_or_dump_method(self):
        opener = intranet().make_opener(proxies={})
        for name in dir(opener):
            self.assertNotIn("save", name.lower())
            self.assertNotIn("dump", name.lower())

    def test_redirect_handler_limit_is_at_most_five(self):
        module = intranet()
        redirects = [h for h in self.handlers(proxies={}) if isinstance(h, module.CheckedRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        self.assertLessEqual(redirects[0].max_redirections, 5)


# ---------------------------------------------------------------------------
# Task 3: 전 페이지 수집, 구조가 바뀌면 멈춤, 비밀번호는 로그인 본문에만
# ---------------------------------------------------------------------------

def paged_routes(extra=None):
    """지급요청 3쪽(쪽 번호 쿼리) + 프로젝트 2쪽(뒤 숫자 꼴)."""
    pay_links = [("/payment/index?page=1", "1"), ("/payment/index?page=2", "2"),
                 ("/payment/index?page=3", "3"), ("/payment/index?page=3", ">"),
                 ("/payment/index?confirm=3", "승인구분 3"), ("/payment/index?search=가상", "정렬"),
                 ("/payment/delete/5101", "삭제"), ("/logout", "로그아웃")]
    routes = site_routes(extra={
        ("GET", "/payment/index"): (200, {}, payment_page(
            [prow(5101, amount="44,000,000"), prow(5102)], links=pay_links)),
        ("GET", "/payment/index?page=2"): (200, {}, payment_page(
            [prow(5102), prow(5103), prow(5104)],
            links=[("/payment/index?page=1", "1"), ("/payment/index?page=2", "2"),
                   ("/payment/index?page=3", "3")])),
        ("GET", "/payment/index?page=3"): (200, {}, payment_page(
            [prow(5105), prow(5106, amount="")],
            links=[("/payment/index?page=1", "1"), ("/payment/index?page=2", "2")])),
        ("GET", "/project/index"): (200, {}, project_page(
            [jrow(26218, 901), jrow(26219, 902)],
            links=[("/project/index/20", "2"), ("/project/index/20", ">")])),
        ("GET", "/project/index/20"): (200, {}, project_page(
            [jrow(26220, 903)], links=[("/project/index", "1")], total=False)),
    })
    routes.update(extra or {})
    return routes


class TestCollectAllPages(unittest.TestCase):
    def run_collect(self, routes=None, **kwargs):
        sleeps = []
        opener, fake = make_fake_opener(paged_routes() if routes is None else routes,
                                        delay=0.3, sleep=sleeps.append)
        result = intranet().collect(opener, USER, PASSWORD, **kwargs)
        return result, fake, sleeps, opener

    def test_every_row_once_from_all_pages(self):
        result, _, _, _ = self.run_collect()
        self.assertEqual([r["번호"] for r in result.payments],
                         ["5101", "5102", "5103", "5104", "5105", "5106"])
        self.assertEqual([r["번호"] for r in result.projects], ["26218", "26219", "26220"])
        self.assertEqual([r["pro_num"] for r in result.projects], ["901", "902", "903"])
        self.assertEqual(result.payment_pages, 3)
        self.assertEqual(result.project_pages, 2)
        self.assertEqual(result.payments[-1]["금액"], "")  # 빈칸은 빈칸 그대로 (0 아님)

    def test_requested_pages_are_exactly_the_page_links(self):
        _, fake, _, _ = self.run_collect()
        self.assertEqual(fake.requested(), [
            ("GET", "/"), ("POST", "/login/submit"),
            ("GET", "/payment/index"), ("GET", "/payment/index?page=2"), ("GET", "/payment/index?page=3"),
            ("GET", "/project/index"), ("GET", "/project/index/20")])
        self.assertEqual(len(set(fake.requested())), len(fake.requested()), "같은 주소를 두 번 요청함")

    def test_filter_javascript_delete_and_view_links_are_not_followed(self):
        _, fake, _, _ = self.run_collect()
        for method, path in fake.requested():
            for bad in ("confirm", "search", "delete", "logout", "/view/", "estimate", "pro_num"):
                self.assertNotIn(bad, path)

    def test_waits_between_requests(self):
        _, fake, sleeps, opener = self.run_collect()
        self.assertEqual(sleeps, [0.3] * (len(fake.calls) - 1))
        self.assertEqual(opener.calls_made, len(fake.calls))

    def test_progress_callback_after_each_page(self):
        seen = []
        self.run_collect(progress=lambda *a: seen.append(a))
        self.assertEqual(seen, [("지급요청", 1, 2), ("지급요청", 2, 4), ("지급요청", 3, 6),
                                ("프로젝트", 1, 2), ("프로젝트", 2, 3)])

    def test_header_alias_and_nbsp_are_accepted(self):
        header = list(PAYMENT_HEADER)
        header[2] = "파트너(페이먼트)"
        header[10] = "사장님 승인"
        routes = site_routes(extra={("GET", "/payment/index"): (200, {}, payment_page(
            [prow(5101)], header=header))})
        result, _, _, _ = self.run_collect(routes)
        self.assertEqual([r["번호"] for r in result.payments], ["5101"])

    def test_notice_row_and_total_row_are_not_data(self):
        page = payment_page([prow(5101)]).replace(
            "</tbody>", "<tr><td colspan='12'>합계</td></tr><tr><td colspan='12'></td></tr></tbody>")
        result, _, _, _ = self.run_collect(site_routes(extra={("GET", "/payment/index"): (200, {}, page)}))
        self.assertEqual([r["번호"] for r in result.payments], ["5101"])


def collect_raises(test, routes, **kwargs):
    """routes로 수집을 돌려 예외를 돌려준다(없으면 실패)."""
    opener, fake = make_fake_opener(routes)
    with test.assertRaises(Exception) as ctx:
        intranet().collect(opener, USER, PASSWORD, **kwargs)
    return ctx.exception, fake


class TestStructureStops(unittest.TestCase):
    def payment_route(self, **kwargs):
        rows = kwargs.pop("rows", [prow(5101), prow(5102)])
        return site_routes(extra={("GET", "/payment/index"): (200, {}, payment_page(rows, **kwargs))})

    def test_header_without_amount_names_the_difference(self):
        module = intranet()
        header = [h for h in PAYMENT_HEADER if h != "금액"]
        exc, _ = collect_raises(self, self.payment_route(header=header))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("금액", str(exc))
        self.assertIn("지급요청 목록 머리글", str(exc))

    def test_extra_header_column_is_named(self):
        module = intranet()
        exc, _ = collect_raises(self, self.payment_route(header=PAYMENT_HEADER + ["비고"]))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("비고", str(exc))

    def test_project_header_difference_is_named(self):
        module = intranet()
        header = [h for h in PROJECT_HEADER if h != "실행가"]
        exc, _ = collect_raises(self, site_routes(extra={
            ("GET", "/project/index"): (200, {}, project_page([jrow(1, 11)], header=header))}))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("프로젝트 목록 머리글", str(exc))
        self.assertIn("실행가", str(exc))

    def test_list_page_showing_login_form_is_login_failed(self):
        module = intranet()
        exc, _ = collect_raises(self, site_routes(extra={("GET", "/payment/index"): (200, {}, login_page())}))
        self.assertIsInstance(exc, module.LoginFailed)

    def test_zero_rows_stop(self):
        module = intranet()
        exc, _ = collect_raises(self, self.payment_route(rows=[]))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("0건", str(exc))

    def test_zero_rows_with_notice_row_stops_too(self):
        module = intranet()
        page = payment_page([]).replace(
            "<tbody></tbody>", "<tbody><tr><td colspan='12'>등록된 자료가 없습니다</td></tr></tbody>")
        exc, _ = collect_raises(self, site_routes(extra={("GET", "/payment/index"): (200, {}, page)}))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("0건", str(exc))

    def test_cell_count_differs_from_header(self):
        module = intranet()
        short = [prow(5101)[:10], prow(5102)[:10]]  # 값 10개 + 삭제 칸 = 11칸, 머리글은 12칸
        exc, _ = collect_raises(self, self.payment_route(rows=short))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("칸 수", str(exc))

    def test_one_bad_row_among_good_rows_also_stops(self):
        module = intranet()
        exc, _ = collect_raises(self, self.payment_route(rows=[prow(5101), prow(5102)[:10]]))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("칸 수", str(exc))

    def test_row_without_number_stops(self):
        module = intranet()
        bad = prow(5102)
        bad[0] = ""
        exc, _ = collect_raises(self, self.payment_route(rows=[prow(5101), bad]))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("번호", str(exc))

    def test_max_pages_reached_with_pages_left(self):
        module = intranet()
        exc, fake = collect_raises(self, paged_routes(), max_pages=2)
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("최대 페이지 수 2", str(exc))
        self.assertNotIn(("GET", "/payment/index?page=3"), fake.requested())

    def test_unknown_paging_query_name_stops_without_requesting_it(self):
        module = intranet()
        links = [("/payment/index?pg2=2", "2"), ("/payment/index?pg2=3", "3")]
        exc, fake = collect_raises(self, self.payment_route(links=links))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("pg2", str(exc))
        self.assertEqual([r for r in fake.requested() if "pg2" in r[1]], [])

    def test_page_links_with_two_years_stop_without_requesting_either(self):
        """쪽 링크가 서로 다른 gyear 를 붙이면 어느 목록인지 알 수 없어 멈춘다."""
        links = [("/payment/index?gyear=2026&page=2", "2"), ("/payment/index?gyear=2025&page=2", "작년")]
        first = payment_page([prow(5101), prow(5102)], links=links)
        routes = site_routes(extra={
            ("GET", "/payment/index"): (200, {}, first),
            ("GET", "/payment/index?gyear=2026"): (200, {}, first),
            ("GET", "/payment/index?gyear=2026&page=2"): (200, {}, payment_page([prow(5103)])),
        })
        exc, fake = collect_raises(self, routes)   # 같은 이름에 값이 둘이면 어느 것도 붙이지 않고 멈춤
        self.assertIsInstance(exc, intranet().StructureMismatch)
        self.assertEqual([r for r in fake.requested() if "gyear" in r[1]], [])

    def test_page_link_adding_gyear_is_followed_when_first_page_is_the_same(self):
        """실제 인트라넷 (2026-11-04): 쪽 링크에만 gyear=2026 이 붙음 → 그 값을 붙인 첫 쪽이 같으면 그 주소로 모든 쪽을 읽는다."""
        links = [("/payment/index?gyear=2026&page=2", "2")]
        first = payment_page([prow(5101), prow(5102)], links=links)
        routes = site_routes(extra={
            ("GET", "/payment/index"): (200, {}, first),
            ("GET", "/payment/index?gyear=2026"): (200, {}, first),
            ("GET", "/payment/index?gyear=2026&page=2"): (200, {}, payment_page(
                [prow(5103)], links=[("/payment/index?gyear=2026&page=1", "1")])),
        })
        opener, fake = make_fake_opener(routes)
        res = intranet().collect(opener, USER, PASSWORD)
        self.assertEqual([r["번호"] for r in res.payments], ["5101", "5102", "5103"])
        self.assertIn(("GET", "/payment/index?gyear=2026&page=2"), fake.requested())

    def test_page_link_adding_gyear_stops_when_first_page_differs(self):
        module = intranet()
        links = [("/payment/index?gyear=2026&page=2", "2")]
        routes = site_routes(extra={
            ("GET", "/payment/index"): (200, {}, payment_page([prow(5101), prow(5102)], links=links)),
            ("GET", "/payment/index?gyear=2026"): (200, {}, payment_page([prow(5101)], links=links)),
        })
        exc, fake = collect_raises(self, routes)
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("첫 쪽 내용이 달라져", str(exc))
        self.assertNotIn(("GET", "/payment/index?gyear=2026&page=2"), fake.requested())

    def test_login_page_without_form1(self):
        module = intranet()
        exc, fake = collect_raises(self, site_routes(extra={("GET", "/"): (200, {}, login_page(form_name="loginform"))}))
        self.assertIsInstance(exc, module.StructureMismatch)
        self.assertIn("form1", str(exc))
        self.assertEqual(fake.paths(), [("GET", "/")])


class TestCredentialsNeverKept(unittest.TestCase):
    SECRETS = (USER, PASSWORD, PASSWORD_ENC, urllib.parse.quote(USER), urllib.parse.quote_plus(USER))

    def test_password_is_only_in_the_one_login_post_body(self):
        opener, fake = make_fake_opener(paged_routes())
        intranet().collect(opener, USER, PASSWORD)
        with_password = [c for c in fake.calls if PASSWORD_ENC.encode() in (c[2] or b"")]
        self.assertEqual(len(with_password), 1)
        self.assertEqual((with_password[0][0], urllib.parse.urlsplit(with_password[0][1]).path),
                         ("POST", "/login/submit"))
        for method, url, body, cookie in fake.calls:
            for secret in self.SECRETS:
                self.assertNotIn(secret, url)
                self.assertNotIn(secret, cookie or "")
        for method, url, body, cookie in fake.calls:
            if method != "POST":
                self.assertIsNone(body)

    def test_collector_touches_no_file(self):
        opener, fake = make_fake_opener(paged_routes())
        with mock.patch.object(builtins, "open", side_effect=AssertionError("파일 열기")), \
                mock.patch.object(os, "makedirs", side_effect=AssertionError("폴더 만들기")):
            result = intranet().collect(opener, USER, PASSWORD)
        self.assertEqual(len(result.payments), 6)

    def test_result_rows_and_opener_hold_no_credentials(self):
        opener, _ = make_fake_opener(paged_routes())
        result = intranet().collect(opener, USER, PASSWORD)
        texts = [repr(result), repr(vars(opener)), repr(result.login_info)]
        for row in result.payments + result.projects:
            texts.extend(row.values())
        for text in texts:
            for secret in self.SECRETS:
                self.assertNotIn(secret, text)

    def test_exceptions_hold_no_credentials(self):
        module = intranet()
        bad_header = [h for h in PAYMENT_HEADER if h != "금액"]
        scenarios = {
            "header": site_routes(extra={("GET", "/payment/index"): (200, {}, payment_page(
                [prow(1)], header=bad_header))}),
            "login": site_routes(extra={("GET", "/payment/index"): (200, {}, login_page())}),
            "blocked": site_routes(extra={("GET", "/payment/index"): (302, {"Location": "/confirm/payment/1"}, "")}),
            "zero": site_routes(extra={("GET", "/payment/index"): (200, {}, payment_page([]))}),
            "cells": site_routes(extra={("GET", "/payment/index"): (200, {}, payment_page([prow(1)[:10]]))}),
            "form1": site_routes(extra={("GET", "/"): (200, {}, login_page(form_name="x"))}),
        }
        kinds = {"header": module.StructureMismatch, "login": module.LoginFailed,
                 "blocked": module.BlockedRequest, "zero": module.StructureMismatch,
                 "cells": module.StructureMismatch, "form1": module.StructureMismatch}
        for name, routes in scenarios.items():
            with self.subTest(name):
                exc, _ = collect_raises(self, routes)
                self.assertIsInstance(exc, kinds[name])
        exc, _ = collect_raises(self, paged_routes(), max_pages=2)
        self.assertIsInstance(exc, module.StructureMismatch)
        for name, routes in list(scenarios.items()) + [("pages", paged_routes())]:
            with self.subTest("secret-" + name):
                exc, _ = collect_raises(self, routes, **({"max_pages": 2} if name == "pages" else {}))
                for secret in self.SECRETS:
                    self.assertNotIn(secret, str(exc))
                    self.assertNotIn(secret, repr(exc))


if __name__ == "__main__":
    unittest.main()
