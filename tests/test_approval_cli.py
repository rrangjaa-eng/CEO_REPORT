"""승인검토.py 수집 실행(--수집 함)·구조 점검(--구조점검)·실행 파일(.bat) 테스트.

네트워크는 쓰지 않는다: 가짜 transport(tests/test_intranet.py)가 인트라넷을 대신한다.
ID·비밀번호는 시험용 가짜 값이며, 어떤 실행에서도 파일·출력·주소에 남지 않는지 훑어 본다.
다른 시험 파일에서는 함수와 상수만 가져온다(TestCase 클래스는 가져오지 않는다).
"""
import contextlib
import csv
import datetime as dt
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

from sample_input import refresh as refresh_sample  # noqa: E402
from test_approval import (FAKE_PAYMENTS, FAKE_PROJECTS, SAMPLE, as_dicts, element_html, load_approval_cli,  # noqa: E402
                           text_of, write_fake_snapshot)
from test_intranet import (PASSWORD, USER, FakeTransport, PAYMENT_HEADER, login_page,  # noqa: E402
                           make_fake_opener, payment_page, project_page, site_routes)

HEADLINE = "전부 승인 시 최저 잔액 90.5 백만원 · 2026-12-25"


def setUpModule():
    refresh_sample()  # 샘플은 임시 폴더에 쓴다 (실제 입력 폴더를 건드리지 않음)


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
        return ["--수집", "함", "--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", self.root, "--출력", self.out] + list(extra)

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
            self, ["--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", self.root, "--출력", self.out, "--열기", "안함"])
        self.assertEqual(rc, 0, out)
        for name in ("input", "getpass", "opener"):
            mocks[name].assert_not_called()
        mocks["browser"].assert_not_called()
        self.assertEqual(fake.calls, [])
        self.assertIn("(마지막 스냅숏)", out)

    def test_explicit_no_collect_after_collect_flag_wins(self):
        write_fake_snapshot(self.root)
        rc, out, err, fake, mocks = run_cli(
            self, ["--수집", "함", "--수집", "안함", "--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", self.root,
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


# CR-02: 인트라넷 글자(행사명·파트너·클라이언트 등)의 주민번호 모양 값은 화면·CSV·stdout 어디에도 나가지 않는다 (D-36).
# 가상 값만 쓴다. 'RRN_PARTS' 의 두 조각은 다른 가상 자료에 나오지 않는 숫자다.
RRN_PARTS = ("770707", "2345678")
RRN_PAYMENTS = [
    ["5201", "[26201] 강사료 홍길동 770707-2345678", "홍길동 770707 - 2345678", "2026-10-30 10:00:00", "2026-11-20",
     "800,000", "2026-11-13", "홍길동", "승인", "승인", "미승인"],
    ["5202", "[26201] 강사료 770707–2345678", "가상강사 770707.2345678", "2026-10-30 11:00:00", "2026-11-20",
     "300,000", "", "홍길동", "승인", "승인", "승인"],
    ["5203", "[26220] 강사료 7707072345678", "가상강사 770707/2345678", "2026-10-30 11:00:00", "2026-11-20",
     "1,100,000", "2026-11-13", "홍길동", "승인", "승인", "반려"],
]
RRN_PROJECT = ["26230", "개인고객 770707-2345678", "홍길동", "PO-9", "2026-11-20", "[26230] 개인 강의 770707 2345678", "1국",
               "1팀", "홍길동", "미발행", "1,000,000", "1,100,000", "900,000", "18.2%", "승인", "승인", "승인", "승인", "905"]


def assert_no_rrn(test, tmp, captured):
    """tmp 아래 모든 파일과 붙잡은 출력에 주민번호 조각이 없어야 한다 (가려졌다는 표시는 남아도 된다)."""
    seen = 0
    for dirpath, _, files in os.walk(tmp):
        for name in files:
            with open(os.path.join(dirpath, name), "rb") as f:
                data = f.read().decode("utf-8", "replace")
            seen += 1
            for part in RRN_PARTS:
                test.assertNotIn(part, data, "파일에 남음: %s" % name)
    for text in captured:
        for part in RRN_PARTS:
            test.assertNotIn(part, text)
    return seen


def unmasked_snapshot(snap, payments, projects):
    """write_snapshot 이 가린 값을 원래 값으로 되돌려 쓴다 (가리기 전 버전이 쓴 스냅숏 흉내). 프로젝트 줄은 덧붙인다."""
    for name, rows, append in (("지급요청.csv", payments, False), ("프로젝트목록.csv", projects, True)):
        path = os.path.join(snap, name)
        with open(path, encoding="utf-8-sig", newline="") as f:
            table = list(csv.reader(f))
        stamp = table[1][0]
        by_no = dict((r[0], r) for r in rows)
        table = [table[0]] + [([t[0]] + by_no[t[1]]) if t[1] in by_no else t for t in table[1:]]
        if append:
            table += [[stamp] + list(r) for r in rows]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(table)
    if projects:
        info = os.path.join(snap, "수집정보.csv")
        with open(info, encoding="utf-8-sig", newline="") as f:
            table = list(csv.reader(f))
        table = [[k, str(int(v) + len(projects))] if k == "프로젝트_건수" else [k, v] for k, v in table]
        with open(info, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(table)


class TestIntranetRrnMasked(_TmpMixin, unittest.TestCase):
    def setUp(self):
        self.make_tmp()

    def test_collect_run_masks_intranet_text_in_snapshot_page_and_stdout(self):
        site = fake_site({("GET", "/payment/index"): (200, {}, payment_page(FAKE_PAYMENTS + RRN_PAYMENTS)),
                          ("GET", "/project/index"): (200, {}, project_page(FAKE_PROJECTS + [RRN_PROJECT]))})
        rc, out, err, fake, mocks = run_cli(self, self.argv(), site=site)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(assert_no_rrn(self, self.tmp, [out, err]), 4)  # 스냅숏 CSV 3개 + 화면 1개
        snap = snapshot_module().read_snapshot(os.path.join(self.root, entries(self.root)[0]))
        names = dict((p["번호"], (p["행사명"], p["파트너"])) for p in snap.payments)
        self.assertEqual(names["5201"], ("[26201] 강사료 홍길동 ******-*******", "홍길동 ******-*******"))
        self.assertEqual(names["5201"][0][:7], "[26201]")  # 프로젝트 코드는 그대로 읽힌다
        with open(os.path.join(self.out, entries(self.out)[0]), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("******-*******", page)

    def test_crawler_rows_are_masked_where_they_are_read(self):
        opener = intranet().make_opener(
            transport=FakeTransport(site_routes(RRN_PAYMENTS, [RRN_PROJECT])), proxies={}, delay=0,
            sleep=lambda s: None)
        result = intranet().collect(opener, USER, PASSWORD)
        self.assertNotIn(RRN_PARTS[0], repr(result.payments) + repr(result.projects))
        self.assertNotIn(RRN_PARTS[1], repr(result.payments) + repr(result.projects))
        self.assertEqual(result.projects[0]["클라이언트"], "개인고객 ******-*******")

    def test_write_snapshot_masks_whatever_it_is_given(self):
        s = snapshot_module()
        path = s.write_snapshot(self.root, dt.datetime(2026, 11, 2, 9, 0, 0),
                                as_dicts(RRN_PAYMENTS, s.PAYMENT_COLUMNS), as_dicts([RRN_PROJECT], s.PROJECT_COLUMNS))
        self.assertEqual(assert_no_rrn(self, path, []), 3)

    def test_an_older_unmasked_snapshot_is_masked_on_the_page(self):
        snap = write_fake_snapshot(self.root, extra=RRN_PAYMENTS)
        # 이전 버전이 가리지 않고 쓴 스냅숏을 흉내 낸다: CSV 에 원래 값을 다시 써 넣는다
        unmasked_snapshot(snap, RRN_PAYMENTS, [RRN_PROJECT])
        with open(os.path.join(snap, "지급요청.csv"), encoding="utf-8-sig") as f:
            self.assertIn(RRN_PARTS[0], f.read())  # 시험 준비 확인: 디스크의 옛 스냅숏에는 원래 값이 있다
        rc, out, err, fake, mocks = run_cli(
            self, ["--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", self.root, "--출력", self.out, "--열기", "안함"])
        self.assertEqual(rc, 0, out + err)
        assert_no_rrn(self, self.out, [out, err])
        with open(os.path.join(self.out, entries(self.out)[0]), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("강사료 홍길동 ******-*******", page)
        self.assertIn("개인 강의 ******-*******", page)


class TestDuplicateNumbers(_TmpMixin, unittest.TestCase):
    """WR-07: 같은 번호의 다른 줄은 조용히 버리지 않고 멈춘다. 같은 줄을 두 번 읽은 것은 문제가 아니다."""

    def setUp(self):
        self.make_tmp()

    def collect(self, payments):
        opener = intranet().make_opener(transport=FakeTransport(site_routes(payments, FAKE_PROJECTS)), proxies={},
                                        delay=0, sleep=lambda s: None)
        return intranet().collect(opener, USER, PASSWORD)

    def test_same_number_with_different_cells_stops_the_crawl(self):
        other = list(FAKE_PAYMENTS[2])
        other[5] = "1,000"
        with self.assertRaises(intranet().StructureMismatch) as cm:
            self.collect(list(FAKE_PAYMENTS) + [other])
        self.assertIn("번호가 같은데 내용이 다른 줄 1건 (5103)", str(cm.exception))

    def test_the_same_row_read_twice_is_kept_once(self):
        result = self.collect(list(FAKE_PAYMENTS) + [list(FAKE_PAYMENTS[2])])
        self.assertEqual([p["번호"] for p in result.payments], [r[0] for r in FAKE_PAYMENTS])

    def test_cli_stops_on_a_snapshot_with_a_repeated_number(self):
        write_fake_snapshot(self.root, extra=[list(FAKE_PAYMENTS[0])])
        rc, out, err, fake, mocks = run_cli(
            self, ["--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", self.root, "--출력", self.out, "--열기", "안함"])
        self.assertEqual(rc, 2, out)
        self.assertIn("스냅숏을 읽지 못했습니다", out)
        self.assertIn("번호가 겹치는 줄 2건 (1201)", out)
        self.assertEqual(entries(self.out), [])


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


# ---------------------------------------------------------------------------
# Task 2: 구조 점검
# ---------------------------------------------------------------------------

PAGED_LINKS = [("/payment/index?page=2", "2"), ("/payment/index?page=3", "3"),
               ("/payment/index?confirm=3", "승인 대기")]


class TestStructureCheck(_TmpMixin, unittest.TestCase):
    def setUp(self):
        self.make_tmp()

    def report(self, extra=None):
        opener, fake = make_fake_opener(fake_site(extra))
        rep = intranet().structure_report(opener, USER, PASSWORD)
        return rep, fake

    def check_argv(self):
        return ["--구조점검", "--수집폴더", self.root, "--출력", self.out]

    def check(self, extra=None, **kw):
        cli = load_approval_cli()
        patches = [mock.patch.object(cli, "write_snapshot"), mock.patch.object(cli, "make_screen")]
        rc, out, err, fake, mocks = run_cli(self, self.check_argv(), site=fake_site(extra), patches=patches, **kw)
        self.assertEqual(entries(self.tmp), [], "구조 점검이 파일이나 폴더를 만듦")
        self.assertFalse(os.path.exists(self.root))
        self.assertFalse(os.path.exists(self.out))
        mocks["browser"].assert_not_called()
        self.assertNotIn("Traceback", out + err)
        sweep(self, self.tmp, [out, err], fake)
        return rc, out, err, fake

    def test_report_on_the_fake_site(self):
        rep, fake = self.report()
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["login"], {"status": 302, "redirect_path": "/main"})
        pay = rep["payment"]
        self.assertTrue(pay["header_ok"])
        self.assertEqual((pay["missing"], pay["extra"], pay["rows"], pay["bad_rows"]), ([], [], 9, 0))
        self.assertEqual(pay["page_links"], {"query": {}, "path_number": 0, "max_number": None})
        self.assertEqual(pay["unfollowed_query_names"], [])
        self.assertEqual(len(pay["rows_data"]), 9)
        proj = rep["project"]
        self.assertTrue(proj["header_ok"])
        self.assertEqual((proj["rows"], proj["total_row"], proj["pro_num_links"]), (4, True, 4))
        self.assertEqual(fake.paths(), [("GET", "/"), ("POST", "/login/submit"),
                                        ("GET", "/payment/index"), ("GET", "/project/index")])
        self.assertNotIn(PASSWORD, repr(rep))
        self.assertNotIn(USER, repr(rep))

    def test_page_links_are_counted_not_followed(self):
        rep, fake = self.report({("GET", "/payment/index"): (200, {}, payment_page(FAKE_PAYMENTS, links=PAGED_LINKS))})
        pay = rep["payment"]
        self.assertEqual(pay["page_links"]["query"], {"page": 2})
        self.assertEqual(pay["page_links"]["max_number"], 3)
        self.assertEqual(pay["unfollowed_query_names"], ["confirm"])
        self.assertEqual(len(fake.calls), 4)
        self.assertTrue(rep["ok"])

    def test_path_number_links_are_counted(self):
        links = [("/payment/index/2", "2"), ("/payment/index/7", "7")]
        rep, fake = self.report({("GET", "/payment/index"): (200, {}, payment_page(FAKE_PAYMENTS, links=links))})
        self.assertEqual(rep["payment"]["page_links"], {"query": {}, "path_number": 2, "max_number": 7})
        self.assertEqual(len(fake.calls), 4)

    def test_header_without_amount_is_reported_not_raised(self):
        header = [h for h in PAYMENT_HEADER if h != "금액"]
        rep, _ = self.report({("GET", "/payment/index"): (200, {}, payment_page(FAKE_PAYMENTS, header=header))})
        self.assertFalse(rep["ok"])
        self.assertFalse(rep["payment"]["header_ok"])
        self.assertEqual(rep["payment"]["missing"], ["금액"])
        self.assertTrue(rep["project"]["header_ok"])

    def test_login_form_on_list_page_raises(self):
        with self.assertRaises(intranet().LoginFailed):
            self.report({("GET", "/payment/index"): (200, {}, login_page())})

    def test_blocked_redirect_still_raises(self):
        with self.assertRaises(intranet().BlockedRequest):
            self.report({("GET", "/project/index"): (302, {"Location": "/confirm/project/1"}, "")})

    def test_unknown_paging_is_not_ok(self):
        links = [("/payment/index?gyear=2026&page=2", "2")]
        rep, _ = self.report({("GET", "/payment/index"): (200, {}, payment_page(FAKE_PAYMENTS, links=links))})
        self.assertFalse(rep["ok"])
        self.assertIn("gyear", rep["payment"]["paging_stop"])

    def test_cli_prints_counts_and_writes_nothing(self):
        rc, out, err, fake = self.check()
        self.assertEqual(rc, 0, out + err)
        for line in ("로그인: 성공", "지급요청 목록 머리글: 일치", "지급요청 1쪽: 9건", "프로젝트 목록 머리글: 일치",
                     "프로젝트 1쪽: 4건", "Total 줄 있음", "금액 미확인 1건", "등록일 해석 불가 0건",
                     "프로젝트 코드 없음 0건", "구조 점검 결과: 예상과 일치", "파일을 만들지 않았습니다"):
            self.assertIn(line, out)
        self.assertEqual(len(fake.calls), 4)

    def test_cli_does_not_print_the_login_redirect_path(self):
        # IN-09: 로그인 뒤 이동 위치에 ID가 들어 있어도 화면에 찍지 않는다 (있음/없음만)
        rc, out, err, fake = self.check({("POST", "/login/submit"): (302, {"Location": "/main/someid42"}, "")})
        self.assertIn("로그인: 성공", out)
        self.assertIn("이동 위치 있음", out)
        self.assertNotIn("someid42", out + err)

    def test_cli_prints_no_row_values(self):
        rc, out, err, fake = self.check()
        for value in ("가상음향", "가상 컨퍼런스", "44,000,000", "가상고객A", "홍길동"):
            self.assertNotIn(value, out + err)

    def test_cli_shows_link_forms_and_page_cap(self):
        rc, out, err, fake = self.check({("GET", "/payment/index"): (200, {}, payment_page(FAKE_PAYMENTS, links=PAGED_LINKS))})
        self.assertEqual(rc, 0, out)
        self.assertIn("지급요청 쪽 링크 최대 번호 3 (수집 상한 --최대페이지 300)", out)
        self.assertIn("confirm", out)
        self.assertEqual(len(fake.calls), 4)

    def test_cli_reports_header_difference_with_3(self):
        header = [h for h in PAYMENT_HEADER if h != "금액"]
        rc, out, err, fake = self.check({("GET", "/payment/index"): (200, {}, payment_page(FAKE_PAYMENTS, header=header))})
        self.assertEqual(rc, 3, out)
        self.assertIn("지급요청 목록 머리글: 다름", out)
        self.assertIn("없음: 금액", out)
        self.assertIn("구조 점검 결과: 예상과 다름", out)

    def test_cli_stops_map_to_exit_codes(self):
        cases = [
            (3, "로그인 실패", {("GET", "/payment/index"): (200, {}, login_page())}),
            (4, "허용 목록 밖 요청을 막고 멈췄습니다", {("GET", "/payment/index"): (302, {"Location": "/confirm/payment/1"}, "")}),
            (5, "인트라넷 연결 실패", {("GET", "/"): urllib.error.URLError("가상 연결 거부")}),
            (6, "수집 중 예상하지 못한 오류: ValueError", {("GET", "/project/index"): ValueError("가상 %s" % PASSWORD)}),
        ]
        for rc_want, text, extra in cases:
            with self.subTest(text):
                rc, out, err, fake = self.check(extra)
                self.assertEqual(rc, rc_want, out + err)
                self.assertIn(text, out)

    def test_cli_empty_password_stops_before_any_request(self):
        rc, out, err, fake = self.check(password="")
        self.assertEqual(rc, 2)
        self.assertEqual(fake.calls, [])


# ---------------------------------------------------------------------------
# Task 3: 실행_승인검토.bat
# ---------------------------------------------------------------------------

class TestApprovalLauncher(unittest.TestCase):
    """cmd.exe는 여기서 실행할 수 없어 파일 모양과 줄 순서만 본다. Windows 실행은 사람이 확인한다(끝 점검 목록)."""
    NAME = "실행_승인검토.bat"
    RUN = "%PY% 승인검토.py --수집 함 %*"

    def raw(self, name=None):
        path = os.path.join(ROOT, name or self.NAME)
        self.assertTrue(os.path.exists(path), name or self.NAME)
        with open(path, "rb") as f:
            return f.read()

    def lines(self, name=None):
        return self.raw(name).decode("utf-8").split("\r\n")

    def test_bytes_are_utf8_crlf_without_bom(self):
        raw = self.raw()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOM")
        self.assertGreater(raw.count(b"\n"), 0)
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"), "모든 줄이 CRLF")
        raw.decode("utf-8")

    def test_content_markers_and_chcp_first(self):
        text = self.raw().decode("utf-8")
        for needle in ("chcp 65001", "%~dp0", "승인검토.py --수집 함 %*", "python --version", "py -3",
                       "python.org", "pause"):
            self.assertIn(needle, text, needle)
        first_non_ascii = min(i for i, ch in enumerate(text) if ord(ch) > 127)
        self.assertLess(text.index("chcp 65001"), first_non_ascii)

    def test_run_line_exit_code_flow(self):
        lines = self.lines()
        run = [i for i, ln in enumerate(lines) if ln.startswith("%PY% 승인검토.py")]
        self.assertEqual(len(run), 1)
        self.assertEqual(lines[run[0]], self.RUN)
        checks = [i for i, ln in enumerate(lines) if "version_info" in ln and "(3, 8)" in ln]
        self.assertEqual(len(checks), 2)
        self.assertTrue(all(i < run[0] for i in checks))
        ok = [i for i, ln in enumerate(lines) if "완료했습니다" in ln]
        fail = [i for i, ln in enumerate(lines) if "오류가 발생했습니다" in ln]
        self.assertEqual((len(ok), len(fail)), (1, 1))
        guard = [i for i, ln in enumerate(lines) if i > run[0] and re.match(r'if (not )?"%RC%"==["]?0', ln, re.I)]
        self.assertTrue(guard, "RC 검사가 없음")
        self.assertLess(guard[0], ok[0])
        self.assertLess(guard[0], fail[0])
        self.assertEqual(lines[ok[0] - 1].strip().upper(), ":OK")
        self.assertTrue(any(ln.strip() == "exit /b %RC%" for ln in lines))

    def test_never_touches_the_password(self):
        lines = self.lines()
        for ln in lines:
            self.assertNotIn("set /p", ln.lower())
        run = next(ln for ln in lines if ln.startswith("%PY% 승인검토.py"))
        for token in ("비밀", "pass", "pw"):
            self.assertNotIn(token, run.lower())
        text = "\n".join(lines).lower()
        self.assertNotIn("%password%", text)
        self.assertNotIn("%pw%", text)

    def test_tells_the_user_what_will_be_asked(self):
        lines = self.lines()
        run = next(i for i, ln in enumerate(lines) if ln.startswith("%PY% 승인검토.py"))
        notes = [ln for ln in lines[:run] if ln.lower().startswith("echo") and "ID" in ln and "비밀번호" in ln
                 and "보이지 않" in ln]
        self.assertEqual(len(notes), 1, notes)

    def test_only_three_lines_differ_from_the_weekly_launcher(self):
        # 보고서 실행 파일만 가용일 질문 4줄이 있다 (문서로 전달, 사용자 2026-11-03). 그 줄을 빼고 비교한다
        weekly = [ln.replace(" %PICKARG%", "") for ln in self.lines("실행_주간.bat") if "PICK" not in ln or ln.startswith("%PY%")]
        mine = self.lines()
        added = [ln for ln in mine if ln not in weekly]
        removed = [ln for ln in weekly if ln not in mine]
        self.assertEqual(len(added), 3, added)
        self.assertEqual(len(removed), 2, removed)
        self.assertIn(self.RUN, added)
        self.assertIn("%PY% 보고서.py 주간 %*", removed)
        self.assertIn("echo 완료했습니다. 위 메시지를 확인하세요.", added)
        self.assertIn("echo 결과 파일은 출력 폴더에 있습니다.", removed)

    def test_launcher_is_tracked_not_ignored(self):
        rc = subprocess.run(["git", "check-ignore", "-q", self.NAME], cwd=ROOT).returncode
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
