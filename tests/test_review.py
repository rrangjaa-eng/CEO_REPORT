"""착륙 전 검토(pre-landing review) 결함 고정 테스트. 실행: python3 -m unittest discover -s tests

시험 자료는 전부 가상이다. 샘플은 임시 폴더에만 쓴다 (실제 입력 폴더를 건드리지 않음).
"""
import contextlib
import copy
import datetime as dt
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import SCHEMA, load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from ceo_report import util  # noqa: E402

ASOF = dt.date(2026, 11, 2)
FAKE_RRN = "900101-1234567"
MASK = "******-*******"

_MS = None


def make_sample_module():
    """tools/make_sample.py 를 경로로 읽는다 (샘플 자료 S, write)."""
    global _MS
    if _MS is None:
        spec = importlib.util.spec_from_file_location("make_sample_for_review", os.path.join(ROOT, "tools", "make_sample.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MS = m
    return _MS


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def sample_folder(test, edit=None):
    """샘플 자료를 임시 폴더에 쓴다. edit(S)로 고칠 수 있다. 입력 폴더 경로를 돌려준다."""
    ms = make_sample_module()
    S = copy.deepcopy(ms.S)
    if edit:
        edit(S)
    folder = os.path.join(new_tmp(test), "입력")
    for name in SCHEMA:
        ms.write(folder, name, S.get(name, []))
    return folder


def approval_page(test, folder):
    """가상 스냅숏 + 입력 폴더로 승인 검토 화면 HTML."""
    import test_approval as ta
    from ceo_report.approval import build
    from ceo_report.approval_render import render_approval
    from ceo_report.snapshot import read_snapshot
    snap = ta.write_fake_snapshot(os.path.join(new_tmp(test), "수집"))
    A = build(load(folder), read_snapshot(snap), ta.ASOF, ta.NOW, None)
    return render_approval(A, False), A


# ───────────── 1. 주민번호 모양 값은 HTML·출력에 나오지 않는다 ─────────────
def _rrn_edit(S):
    S["입출금내역.csv"][0][7] = "급여 홍길동 " + FAKE_RRN      # 적요 → 1번 묶음 표
    S["자금일정.csv"][0][8] = "퇴직금 " + FAKE_RRN             # 비고 → 6번 묶음 표
    S["자금일정.csv"][0][6] = "거래처 " + FAKE_RRN             # 거래처 → 2번 일정 표
    S["계좌잔액.csv"][0][3] = FAKE_RRN                          # 잔액 칸 오입력 → 입력 확인 목록 글


class TestRrnMasked(unittest.TestCase):
    def test_esc_masks_before_escaping(self):
        self.assertEqual(util.esc("a " + FAKE_RRN + " <b>"), "a " + MASK + " &lt;b&gt;")
        self.assertEqual(util.esc(None), "")
        self.assertEqual(util.esc("2026-11-02 · 1,234,567원"), "2026-11-02 · 1,234,567원")

    def test_reports_mask_every_text_cell(self):
        folder = sample_folder(self, _rrn_edit)
        for kind in ("weekly", "monthly"):
            R = compute(load(folder), kind, ASOF)
            self.assertTrue(any(FAKE_RRN in m for _, _, m in R["s7"]["issues"]))  # 원 자료에는 있다
            for mode in ("ceo", "mgmt"):
                h = render(R, mode)
                self.assertNotIn(FAKE_RRN, h, (kind, mode))
                self.assertNotIn("1234567", h, (kind, mode))
                self.assertIn(MASK, h, (kind, mode))

    def test_approval_screen_masks_issue_lines(self):
        folder = sample_folder(self, _rrn_edit)
        page, A = approval_page(self, folder)
        self.assertTrue(any(FAKE_RRN in str(m) for _, _, m in A["issues"]))
        self.assertNotIn(FAKE_RRN, page)
        self.assertIn(MASK, page)

    def test_report_cli_stdout_masked(self):
        import test_report as tr
        cli = tr.load_cli()
        folder = sample_folder(self, _rrn_edit)
        out = os.path.join(new_tmp(self), "출력")
        buf = io.StringIO()
        with mock.patch.object(cli, "find_browser", return_value="/없는/브라우저"), \
                mock.patch.object(cli, "to_pdf", return_value="PDF 실패: " + FAKE_RRN), \
                contextlib.redirect_stdout(buf):
            rc = cli.main(["주간", "--기준일", "2026-11-02", "--입력", folder, "--출력", out])
        self.assertEqual(rc, 0)
        self.assertNotIn(FAKE_RRN, buf.getvalue())
        self.assertIn(MASK, buf.getvalue())
        for name in os.listdir(out):
            with open(os.path.join(out, name), encoding="utf-8") as f:
                self.assertNotIn(FAKE_RRN, f.read())

    def test_approval_cli_stdout_masked(self):
        import test_approval as ta
        cli = ta.load_approval_cli()
        side = {"table_found": True, "header_ok": False, "missing": ["번호 " + FAKE_RRN], "extra": [FAKE_RRN],
                "first_difference": "3번째 열: " + FAKE_RRN, "rows": 1, "total_row": True, "pro_num_links": 0,
                "bad_rows": 0, "page_links": {"query": {}, "path_number": 0, "max_number": None},
                "unfollowed_query_names": [], "paging_stop": FAKE_RRN, "rows_data": []}
        rep = {"login": {"status": 200, "redirect_path": ""}, "payment": dict(side), "project": dict(side), "ok": False}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.print_structure(rep, 300)
        self.assertNotIn(FAKE_RRN, buf.getvalue())
        self.assertIn(MASK, buf.getvalue())


# ───────────── 2. 음수·괄호 금액이 지급을 입금으로 바꾸지 않는다 ─────────────
def _issue_texts(R):
    return [(f, l, m) for f, l, m in R["s7"]["issues"]]


class TestNegativeOutflow(unittest.TestCase):
    def base(self):
        return compute(load(sample_folder(self)), "weekly", ASOF)

    def test_schedule_payment_bracketed_amount_stays_outflow(self):
        def edit(S):
            S["자금일정.csv"].append(["2026-11-05", "지급", "(30,000,000)", "확정", "회사공통지출", "", "가상업체", "청구서", ""])
            S["자금일정.csv"].append(["2026-11-06", "지급", "-2,000,000", "추정", "회사공통지출", "", "가상업체2", "견적", ""])
        base = self.base()
        R = compute(load(sample_folder(self, edit)), "weekly", ASOF)
        self.assertEqual(R["s2"]["out4_firm"] - base["s2"]["out4_firm"], 30000000)
        self.assertEqual(R["s2"]["out4_est"] - base["s2"]["out4_est"], 2000000)
        self.assertEqual(R["s2"]["in4_firm"], base["s2"]["in4_firm"])
        self.assertEqual(R["s2"]["min"]["firm"][0], base["s2"]["min"]["firm"][0] - 30000000)
        line = len(make_sample_module().S["자금일정.csv"]) + 2  # 머리글 1줄 + 기존 줄 다음
        hits = [x for x in _issue_texts(R) if x[0] == "자금일정.csv" and "(30,000,000)" in x[2]]
        self.assertEqual(len(hits), 1, _issue_texts(R))
        self.assertEqual(hits[0][1], line)
        self.assertIn("음수", hits[0][2])
        self.assertTrue(any(x[0] == "자금일정.csv" and "-2,000,000" in x[2] for x in _issue_texts(R)))

    def test_bank_withdrawal_negative_amount_stays_outflow(self):
        def edit(S):
            S["입출금내역.csv"][0][3] = "-11,000,000"   # 2026-10-27 프로젝트계좌 출금
            S["입출금내역.csv"][1][3] = "(8,000,000)"   # 2026-10-28 운영계좌 출금
        base = self.base()
        R = compute(load(sample_folder(self, edit)), "weekly", ASOF)
        self.assertEqual(R["s1"]["out"], base["s1"]["out"])
        self.assertEqual(R["s1"]["in"], base["s1"]["in"])
        self.assertEqual(R["s1"]["start_calc"], base["s1"]["start_calc"])
        msgs = [x for x in _issue_texts(R) if x[0] == "입출금내역.csv"]
        self.assertTrue(any(x[1] == 2 and "-11,000,000" in x[2] for x in msgs), msgs)
        self.assertTrue(any(x[1] == 3 and "(8,000,000)" in x[2] for x in msgs), msgs)

    def test_project_exec_negative_supply_stays_outflow(self):
        def edit(S):
            for r in S["프로젝트집행.csv"]:
                if r[1] == "음향·조명":           # P26201 요청미지급 40,000,000 + 4,000,000 (2026-11-13)
                    r[4] = "(40,000,000)"
                    r[5] = "-4,000,000"
        base = self.base()
        d = load(sample_folder(self, edit))
        R = compute(d, "weekly", ASOF)
        self.assertEqual(R["s2"]["out4_firm"], base["s2"]["out4_firm"])
        self.assertEqual(R["s2"]["min"], base["s2"]["min"])
        P = {x["id"]: x for x in R["s3"]["projects"]}["P26201"]
        P0 = {x["id"]: x for x in base["s3"]["projects"]}["P26201"]
        self.assertEqual(P["requested"], P0["requested"])
        msgs = [x for x in _issue_texts(R) if x[0] == "프로젝트집행.csv"]
        self.assertTrue(any("공급가액" in x[2] and "(40,000,000)" in x[2] for x in msgs), msgs)
        self.assertTrue(any("부가세" in x[2] and "-4,000,000" in x[2] for x in msgs), msgs)

    def test_approval_schedule_keeps_outflow(self):
        def edit(S):
            S["자금일정.csv"].append(["2026-11-05", "지급", "(30,000,000)", "확정", "회사공통지출", "", "가상업체", "청구서", ""])
        _, A0 = approval_page(self, sample_folder(self))
        _, A = approval_page(self, sample_folder(self, edit))
        self.assertEqual(sum(A["data"]["base_out"]) - sum(A0["data"]["base_out"]), 30000000)


if __name__ == "__main__":
    unittest.main()
