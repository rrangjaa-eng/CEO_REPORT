"""예전 인트라넷(2025~2026.3) CSV 읽기 (사용자 2026-11-05). 값은 모두 가짜."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ceo_report import linking, old_intranet  # noqa: E402

PROJ_HEAD = ["내부번호", "", "번호", "클라이언트", "행사일 ▲", "행사명", "국", "팀", "등록자", "발행일", "계산서", "사전견적",
             "견적금액", "실행가", "수익율", "커미션", "할인", "담당자", "관리팀", "대표이사", "견적", "삭제", "개인정보"]
PAY_HEAD = ["내부번호", "", "번호", "행사명", "파트너(페이먼트)", "등록일", "행사일", "금액", "지급요청일", "등록자",
            "팀장승인", "관리팀승인", "사장님승인", "지불", "삭제"]


def _write(path, head, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


class TestOldIntranet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        d = os.path.join(self.tmp, old_intranet.FOLDER)
        os.makedirs(d)
        p = lambda no, code, day, est, bud: ["7", "", no, "가짜고객", day, "[%s] 가짜행사" % code, "본부", "기획1팀", "갑",
                                            "2025-01-01", "0", est, "0", bud, "10.00%", "0", "Quotation 완료보고",
                                            "승인완료", "승인완료", "반려", "페이먼트보기", "", ""]
        _write(os.path.join(d, "old_projects_2025.csv"), PROJ_HEAD,
               [p("1", "093", "2025-03-01~2025-03-02", "1,000,000", "700,000"),
                p("2", "094", "2025-04-01~2025-04-01", "2,000,000", "1,400,000")])
        _write(os.path.join(d, "old_projects_2026.csv"), PROJ_HEAD,
               [p("1", "093", "2026-02-01~2026-02-03", "3,000,000", "2,100,000"),
                p("2", "26001", "2026-05-01~2026-05-02", "4,000,000", "2,800,000")])
        q = lambda no, code: ["7", "", no, "[%s] 가짜행사" % code, "가짜업체", "2025-03-14 오후 3:12:45", "2025-03-01",
                              "110,000", "2025-03-20", "갑", "수락완료", "수락완료(2025-03-14)", "수락완료(2025-03-15)", "", "Y"]
        _write(os.path.join(d, "old_payments_2025.csv"), PAY_HEAD, [q("1", "093"), q("2", "094")])
        _write(os.path.join(d, "old_payments_2026.csv"), PAY_HEAD, [q("1", "093")])
        _write(os.path.join(d, "old_partners.csv"), ["업체명", "계좌번호"], [["가짜업체", "000-000"]])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_shapes(self):
        old = old_intranet.load(self.tmp)
        self.assertEqual(len(old.projects), 4)
        self.assertEqual(len(old.payments), 3)
        nos = sorted(p["번호"] for p in old.payments)
        self.assertEqual(nos, ["구2025-1", "구2025-2", "구2026-1"])          # 해마다 다시 세는 순번이 겹치지 않음
        pay = old.payments[0]
        self.assertEqual(pay["등록일"], "2025-03-14 15:12:45")
        self.assertEqual(pay["사장님승인"], "승인")
        self.assertEqual(pay["파트너"], "가짜업체")
        self.assertTrue(all(p["번호"] == "" for p in old.projects))        # 화면 순번은 버림
        self.assertNotIn("old_partners.csv", old.files)                      # 업체(계좌) 파일은 읽지 않음

    def test_projects_newer_year_wins_and_current_first(self):
        old = old_intranet.load(self.tmp)
        out = linking.projects_of(None, old)
        self.assertEqual(set(out), {"93", "94", "26001"})
        self.assertEqual(out["93"]["estimate"], 3000000)                     # 2026 [093] 이 2025 [093] 보다 먼저
        self.assertEqual(out["93"]["event_date"], dt.date(2026, 2, 3))      # 행사 끝 날
        self.assertTrue(out["93"]["old"])

        class Snap:
            projects = [{"번호": "26001", "행사명": "[26001] 지금", "사전견적": "9", "실행가": "9", "행사일": "2026-05-02"}]
            payments = []
        now = linking.projects_of(Snap(), old)
        self.assertFalse(now["26001"]["old"])                                # 지금 인트라넷이 우선
        self.assertFalse(now["26001"]["dup"])

    def test_old_requests_for_linking_only(self):
        old = old_intranet.load(self.tmp)
        rq = linking.old_requests(old, dt.date(2026, 11, 5), dt.datetime(2026, 11, 5, 9))
        self.assertEqual(len(rq), 3)
        self.assertTrue(all(r["old"] and r["status"] == "approved" and r["registered"] is not None for r in rq))
        self.assertEqual(sorted(r["code"] for r in rq), ["93", "93", "94"])

    def test_no_folder(self):
        old = old_intranet.load(os.path.join(self.tmp, "없음"))
        self.assertEqual((old.projects, old.payments, old.files), ([], [], []))


class TestOldProjectsDone(unittest.TestCase):
    def test_old_project_before_cutoff_marked_done(self):
        from ceo_report import convert_projects
        projects = {
            "93": {"key": "93", "old": True, "name": "가", "team": "", "client": "", "estimate": 1, "quote": None,
                   "budget": 1, "event_date": dt.date(2026, 2, 3), "dup": False, "estimate_text": "1", "budget_text": "1",
                   "event_text": "2026-02-03"},
            "26001": {"key": "26001", "old": True, "name": "나", "team": "", "client": "", "estimate": 1, "quote": None,
                      "budget": 1, "event_date": dt.date(2026, 5, 2), "dup": False, "estimate_text": "1",
                      "budget_text": "1", "event_text": "2026-05-02"},
            "26002": {"key": "26002", "old": False, "name": "다", "team": "", "client": "", "estimate": 1, "quote": None,
                      "budget": 1, "event_date": dt.date(2026, 1, 2), "dup": False, "estimate_text": "1",
                      "budget_text": "1", "event_text": "2026-01-02"}}
        t = convert_projects.build_projects(projects, {"lines": []}, [])
        state = dict((r["프로젝트번호"], r["상태"]) for r in t.rows)
        self.assertEqual(state, {"93": "완료(예전 인트라넷)", "26001": "", "26002": ""})


if __name__ == "__main__":
    unittest.main()
