"""인트라넷 수집기 테스트. 네트워크는 쓰지 않는다(가짜 transport + 가짜 HTML).

실행: python -m unittest discover -s tests
다른 테스트 파일은 이 파일에서 함수와 클래스(FakeTransport, login_page, payment_page,
project_page)만 가져다 쓴다. TestCase 클래스는 가져가지 않는다.
"""
import http.client
import io
import os
import shutil
import subprocess
import sys
import unittest
import urllib.parse
import urllib.request
import urllib.response
from html import escape

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


if __name__ == "__main__":
    unittest.main()
