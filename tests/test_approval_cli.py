"""승인검토.py 수집 실행(--수집 함)·구조 점검(--구조점검)·실행 파일(.bat) 테스트.

네트워크는 쓰지 않는다: 가짜 transport(tests/test_intranet.py)가 인트라넷을 대신한다.
ID·비밀번호는 시험용 가짜 값이며, 어떤 실행에서도 파일·출력·주소에 남지 않는지 훑어 본다.
다른 시험 파일에서는 함수와 상수만 가져온다(TestCase 클래스는 가져오지 않는다).
"""
import contextlib
import getpass
import http.client
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import warnings
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_approval import (FAKE_PAYMENTS, FAKE_PROJECTS, element_html, load_approval_cli,  # noqa: E402
                           text_of, write_fake_snapshot)
from test_intranet import (PASSWORD, USER, FakeTransport, PAYMENT_HEADER, login_page,  # noqa: E402
                           payment_page, project_page, site_routes)

HEADLINE = "전부 승인 시 최저 잔액 98.2 백만원 · 2026-12-25"


def setUpModule():
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py")], check=True,
                   stdout=subprocess.DEVNULL)


def intranet():
    from ceo_report import intranet as module
    return module


def snapshot_module():
    from ceo_report import snapshot as module
    return module


def fake_site(extra=None):
    """로그인 → 지급요청 1쪽(9건) → 프로젝트 1쪽(4건). extra로 경로를 바꾼다(값이 예외 객체면 던진다)."""
    routes = site_routes(FAKE_PAYMENTS, FAKE_PROJECTS)
    routes.update(extra or {})
    return routes


def run_cli(test, argv, user=USER, password=PASSWORD, site=None, input_mock=None, getpass_mock=None,
            patches=()):
    """승인검토.main을 가짜 입력·가짜 사이트·가짜 브라우저로 돌린다.

    (종료 코드, 표준 출력 글, 표준 오류 글, FakeTransport, {'input','getpass','opener','browser'})를 돌려준다.
    """
    cli = load_approval_cli()
    fake = FakeTransport(fake_site() if site is None else site)
    opener = intranet().make_opener(transport=fake, proxies={}, delay=0, sleep=lambda s: None)
    mocks = {
        "input": input_mock if input_mock is not None else mock.Mock(return_value=user),
        "getpass": getpass_mock if getpass_mock is not None else mock.Mock(return_value=password),
        "opener": mock.Mock(return_value=opener),
        "browser": mock.Mock(),
    }
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch("builtins.input", mocks["input"]))
        stack.enter_context(mock.patch.object(cli.getpass, "getpass", mocks["getpass"]))
        stack.enter_context(mock.patch.object(cli, "make_collector_opener", mocks["opener"]))
        stack.enter_context(mock.patch.object(cli.webbrowser, "open", mocks["browser"]))
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue(), fake, mocks


def secret_forms():
    """ID·비밀번호가 어떤 모양으로든 남았는지 찾을 글자와 바이트."""
    texts = []
    raws = []
    for s in (USER, PASSWORD):
        for v in (s, urllib.parse.quote(s), urllib.parse.quote_plus(s)):
            if v not in texts:
                texts.append(v)
        raws.append(s.encode("utf-8"))
        raws.append(s.encode("cp949"))
    for t in texts:
        raws.append(t.encode("utf-8"))
    return texts, raws


def sweep(test, tmp, captured, fake=None):
    """tmp 아래 모든 파일, 붙잡은 출력, 기록된 주소에 ID·비밀번호가 없어야 한다."""
    texts, raws = secret_forms()
    for dirpath, _, files in os.walk(tmp):
        for name in files:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                data = f.read()
            for raw in raws:
                test.assertNotIn(raw, data, "파일에 남음: %s" % path)
            for t in texts:
                test.assertNotIn(t.encode("utf-8"), name.encode("utf-8"))
    for text in captured:
        data = text.encode("utf-8")
        for t in texts:
            test.assertNotIn(t, text)
        for raw in raws:
            test.assertNotIn(raw, data)
    if fake is not None:
        for method, url, _, _ in fake.calls:
            for t in texts:
                test.assertNotIn(t, url)


def entries(path):
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


class _TmpMixin(object):
    def make_tmp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "수집")
        self.out = os.path.join(self.tmp, "출력")

    def argv(self, *extra):
        return ["--수집", "함", "--기준일", "2026-11-02", "--수집폴더", self.root, "--출력", self.out] + list(extra)

    def assert_nothing_written(self):
        self.assertEqual(entries(self.root), [], "수집 폴더에 무언가 남음")
        self.assertEqual(entries(self.out), [], "출력 폴더에 무언가 남음")


# ---------------------------------------------------------------------------
# Task 1: 수집 실행
# ---------------------------------------------------------------------------

class TestApprovalCollectRun(_TmpMixin, unittest.TestCase):
    def setUp(self):
        self.make_tmp()

    def success(self):
        return run_cli(self, self.argv())

    def test_success_run_writes_one_snapshot_and_one_screen(self):
        rc, out, err, fake, mocks = self.success()
        self.assertEqual(rc, 0, out + err)
        mocks["input"].assert_called_once()
        mocks["getpass"].assert_called_once()
        snaps = entries(self.root)
        self.assertEqual(len(snaps), 1, snaps)
        self.assertRegex(snaps[0], r"^인트라넷_\d{8}_\d{6}$")
        snap = snapshot_module().read_snapshot(os.path.join(self.root, snaps[0]))
        self.assertEqual(len(snap.payments), 9)
        self.assertEqual(len(snap.projects), 4)
        self.assertEqual(snap.info["지급요청_페이지수"], "1")
        htmls = entries(self.out)
        self.assertEqual(len(htmls), 1, htmls)
        self.assertRegex(htmls[0], r"^승인검토_\d{8}_\d{4}\.html$")
        with open(os.path.join(self.out, htmls[0]), encoding="utf-8") as f:
            page = f.read()
        self.assertIn(HEADLINE, text_of(element_html(page, "headline")))
        self.assertIn("(이번 실행에서 수집)", text_of(element_html(page, "start-line")))
        mocks["browser"].assert_called_once()
        target = mocks["browser"].call_args[0][0]
        self.assertTrue(target.startswith("file://"), target)
        self.assertTrue(urllib.parse.unquote(target).endswith(htmls[0]))

    def test_success_prints_summary_line(self):
        rc, out, err, fake, mocks = self.success()
        self.assertEqual(rc, 0)
        self.assertIn("수집 완료: 지급요청 1쪽 9건 · 프로젝트 1쪽 4건", out)
        self.assertRegex(out, r"수집 완료: 지급요청 1쪽 9건 · 프로젝트 1쪽 4건 · \d+\.\d초")
        self.assertIn("지급요청 목록 1쪽 읽음 (누계 9건)", out)
        self.assertIn("프로젝트 목록 1쪽 읽음 (누계 4건)", out)

    def test_exactly_the_allowlisted_requests(self):
        rc, out, err, fake, mocks = self.success()
        self.assertEqual(rc, 0)
        self.assertEqual(fake.paths(), [("GET", "/"), ("POST", "/login/submit"),
                                        ("GET", "/payment/index"), ("GET", "/project/index")])
        for _, path in fake.paths():
            for bad in ("confirm", "/payment/view", "/payment/delete", "/main"):
                self.assertNotIn(bad, path)

    def test_credentials_nowhere_after_success(self):
        rc, out, err, fake, mocks = self.success()
        self.assertEqual(rc, 0)
        sweep(self, self.tmp, [out, err], fake)

    def test_default_mode_never_asks_or_connects(self):
        write_fake_snapshot(self.root)
        rc, out, err, fake, mocks = run_cli(
            self, ["--기준일", "2026-11-02", "--수집폴더", self.root, "--출력", self.out, "--열기", "안함"])
        self.assertEqual(rc, 0, out)
        for name in ("input", "getpass", "opener"):
            mocks[name].assert_not_called()
        mocks["browser"].assert_not_called()
        self.assertEqual(fake.calls, [])
        self.assertIn("(마지막 스냅숏)", out)

    def test_explicit_no_collect_after_collect_flag_wins(self):
        write_fake_snapshot(self.root)
        rc, out, err, fake, mocks = run_cli(
            self, ["--수집", "함", "--수집", "안함", "--기준일", "2026-11-02", "--수집폴더", self.root,
                   "--출력", self.out, "--열기", "안함"])
        self.assertEqual(rc, 0, out)
        mocks["input"].assert_not_called()
        mocks["opener"].assert_not_called()

    def test_no_option_can_carry_credentials(self):
        parser = load_approval_cli().build_parser()
        names = [s for action in parser._actions for s in action.option_strings]
        self.assertIn("--수집", names)
        self.assertIn("--최대페이지", names)
        for name in names:
            self.assertIsNone(re.search(r"비밀|암호|아이디|pass|pw|user|login|^--id$", name, re.I), name)

    def test_default_collect_folder_is_ignored_by_git(self):
        parser = load_approval_cli().build_parser()
        self.assertTrue(parser.get_default("수집폴더").endswith(os.sep + "수집"))
        rc = subprocess.run(["git", "check-ignore", "-q", "수집/인트라넷_20261102_090000/지급요청.csv"],
                            cwd=ROOT).returncode
        self.assertEqual(rc, 0)

    def test_row_keys_have_one_source(self):
        self.assertIs(intranet().PAYMENT_KEYS, snapshot_module().PAYMENT_COLUMNS)
        self.assertIs(intranet().PROJECT_KEYS, snapshot_module().PROJECT_COLUMNS)

    def test_max_pages_option_is_passed_on(self):
        routes = fake_site({("GET", "/payment/index"): (200, {}, payment_page(
            FAKE_PAYMENTS, links=[("/payment/index?page=2", "2")]))})
        rc, out, err, fake, mocks = run_cli(self, self.argv("--최대페이지", "1"), site=routes)
        self.assertEqual(rc, 3, out)
        self.assertIn("최대 페이지 수", out)
        self.assert_nothing_written()

    def test_max_pages_must_be_positive(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                load_approval_cli().build_parser().parse_args(["--최대페이지", "0"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(load_approval_cli().build_parser().parse_args([]).최대페이지, 300)


class TestApprovalCollectStops(_TmpMixin, unittest.TestCase):
    def setUp(self):
        self.make_tmp()

    def stopped(self, rc_want, extra=None, **kw):
        rc, out, err, fake, mocks = run_cli(self, self.argv(), site=fake_site(extra), **kw)
        self.assertEqual(rc, rc_want, out + err)
        self.assert_nothing_written()
        mocks["browser"].assert_not_called()
        self.assertNotIn("Traceback", out + err)
        sweep(self, self.tmp, [out, err], fake)
        return out, err, fake, mocks

    def test_blocked_redirect_stops_with_4(self):
        out, _, fake, _ = self.stopped(4, {("GET", "/payment/index"): (302, {"Location": "/confirm/payment/1"}, "")})
        self.assertIn("허용 목록 밖 요청을 막고 멈췄습니다", out)
        for _, path in fake.paths():
            self.assertNotIn("confirm", path)

    def test_login_failure_stops_with_3(self):
        out, _, _, _ = self.stopped(3, {("GET", "/payment/index"): (200, {}, login_page())})
        self.assertIn("로그인 실패", out)

    def test_header_without_amount_stops_with_3(self):
        header = [h for h in PAYMENT_HEADER if h != "금액"]
        out, _, _, _ = self.stopped(3, {("GET", "/payment/index"): (200, {}, payment_page(FAKE_PAYMENTS, header=header))})
        self.assertIn("금액", out)
        self.assertIn("인트라넷 화면 구조가 예상과 다릅니다", out)

    def test_url_error_stops_with_5(self):
        out, _, _, _ = self.stopped(5, {("GET", "/"): urllib.error.URLError("가상 연결 거부")})
        self.assertIn("인트라넷 연결 실패", out)

    def test_http_protocol_error_stops_with_5(self):
        out, _, _, _ = self.stopped(5, {("GET", "/payment/index"): http.client.BadStatusLine("가상")})
        self.assertIn("인트라넷 연결 실패", out)

    def test_unexpected_error_is_scrubbed_with_6(self):
        out, err, _, _ = self.stopped(6, {("GET", "/project/index"): ValueError("가상 오류 %s" % PASSWORD)})
        self.assertIn("수집 중 예상하지 못한 오류: ValueError", out)
        self.assertIn("***", out)

    def test_ctrl_c_during_collection_stops_with_6(self):
        out, _, _, _ = self.stopped(6, {("GET", "/payment/index"): KeyboardInterrupt()})
        self.assertIn("중단했습니다", out)

    def test_empty_password_stops_with_2_before_any_request(self):
        out, _, fake, _ = self.stopped(2, password="")
        self.assertEqual(fake.calls, [])
        self.assertIn("ID와 비밀번호를 모두 입력해야 합니다", out)

    def test_empty_id_stops_with_2_before_any_request(self):
        out, _, fake, _ = self.stopped(2, user="  ")
        self.assertEqual(fake.calls, [])

    def test_echoing_password_prompt_is_refused(self):
        def echoing(prompt="", stream=None):
            warnings.warn("가상", getpass.GetPassWarning)
            return PASSWORD
        out, _, fake, _ = self.stopped(2, getpass_mock=mock.Mock(side_effect=echoing))
        self.assertEqual(fake.calls, [])
        self.assertIn("비밀번호를 가리고 입력할 수 없는 창입니다", out)

    def test_cancelled_prompts_stop_with_2(self):
        cases = [
            ("id Ctrl+C", dict(input_mock=mock.Mock(side_effect=KeyboardInterrupt()))),
            ("id EOF", dict(input_mock=mock.Mock(side_effect=EOFError()))),
            ("password EOF", dict(getpass_mock=mock.Mock(side_effect=EOFError()))),
            ("password Ctrl+C", dict(getpass_mock=mock.Mock(side_effect=KeyboardInterrupt()))),
        ]
        for label, kw in cases:
            with self.subTest(label):
                out, err, fake, _ = self.stopped(2, **kw)
                self.assertEqual(fake.calls, [])
                self.assertIn("입력을 취소했습니다", out)

    def test_disk_failure_in_write_snapshot_is_7(self):
        cli = load_approval_cli()
        patch = mock.patch.object(cli, "write_snapshot", side_effect=PermissionError("가상"))
        out, _, _, _ = self.stopped(7, patches=[patch])
        self.assertIn("저장 실패", out)
        self.assertNotIn("인트라넷 연결 실패", out)
        self.assertIn("PermissionError", out)

    def test_existing_snapshot_folder_is_7(self):
        cli = load_approval_cli()
        patch = mock.patch.object(cli, "write_snapshot",
                                  side_effect=snapshot_module().SnapshotError("같은 수집 시각의 스냅숏 폴더가 이미 있습니다"))
        out, _, _, _ = self.stopped(7, patches=[patch])
        self.assertIn("저장 실패", out)

    def test_disk_failure_in_make_screen_is_7(self):
        cli = load_approval_cli()
        patch = mock.patch.object(cli, "make_screen", side_effect=OSError("가상"))
        rc, out, err, fake, mocks = run_cli(self, self.argv(), patches=[patch])
        self.assertEqual(rc, 7, out + err)
        self.assertIn("저장 실패", out)
        self.assertNotIn("인트라넷 연결 실패", out)
        mocks["browser"].assert_not_called()
        sweep(self, self.tmp, [out, err], fake)


if __name__ == "__main__":
    unittest.main()
