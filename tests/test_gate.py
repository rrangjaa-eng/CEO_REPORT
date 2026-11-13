"""자금계획서·분개장 미반영이면 대표·팀장 보고를 만들지 않는다 (사용자 2026-11-12: 다시는 이런 실수가 없어야 함)."""
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import gate  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
D = dt.date
ON = {gate.TEST_OFF: ""}


def _R(fp, book_age=1):
    bd = D(2026, 11, 12) - dt.timedelta(days=book_age)
    return {"asof": D(2026, 11, 12), "settings_num": {"위험_자료경과일": 7}, "fundplan": fp,
            "s7": {"asof": [{"name": "회계 반영 (WEHAGO)", "date": bd, "age": book_age}]}}


class TestProblems(unittest.TestCase):
    @mock.patch.dict(os.environ, ON)
    def test_missing_stale_and_ok(self):
        self.assertIn("자금계획서 없음", gate.problems(_R(None))[0])
        self.assertIn("오래", gate.problems(_R({"used": False, "reason": "자금계획서 자료일 2026-10-01이 오래됨"}))[0])
        self.assertIn("분개장 자료일", gate.problems(_R({"used": True, "stamp": D(2026, 11, 12)}, book_age=9))[0])
        self.assertEqual(gate.problems(_R({"used": True, "stamp": D(2026, 11, 12), "months": ["2026-10", "2026-12"]})), [])

    @mock.patch.dict(os.environ, ON)
    def test_book_date_from_convert_facts(self):
        """실제 자료: 자료기준일.csv 가 비어 있어도 변환이 자동분석.json 에 적은 장부 기준일로 판단 (2026-11-13 실제 자료에서 잘못 막힘)."""
        ok = {"used": True, "stamp": D(2026, 11, 12)}
        R = dict(_R(ok), s7={"asof": []}, auto_facts={"book_date": "2026-11-12"})
        self.assertEqual(gate.problems(R), [])
        self.assertIn("분개장 2026-11-12", gate.sources_line(R))
        R["auto_facts"] = {"book_date": "2026-11-01"}
        self.assertIn("11일 전", gate.problems(R)[0])
        R["auto_facts"] = {}
        self.assertIn("모름", gate.problems(R)[0])

    @mock.patch.dict(os.environ, ON)
    def test_sources_line(self):
        R = _R({"used": True, "stamp": D(2026, 11, 12), "months": ["2026-10", "2026-11"]})
        self.assertEqual(gate.sources_line(R), "사용한 자료: 분개장 2026-11-11 · 자금계획서 2026-11-12 받음 (2026-10~2026-11)")
        self.assertIn("자금계획서 미반영", gate.sources_line(_R(None)))

    @mock.patch.dict(os.environ, ON)
    def test_mgmt_report_carries_big_warning_without_fundplan(self):
        R = compute(load(SAMPLE), "weekly", D(2026, 11, 6))   # 예시 자료엔 자금계획서가 없다
        page = render(R, "mgmt")
        self.assertIn("class='gate'", page)
        self.assertIn("자금계획서 미반영", page)


class TestCli(unittest.TestCase):
    def test_ceo_and_team_reports_are_not_made_without_fundplan(self):
        with tempfile.TemporaryDirectory() as t:
            inp, out = os.path.join(t, "입력"), os.path.join(t, "출력")
            shutil.copytree(SAMPLE, inp)
            env = dict(os.environ)
            env.pop(gate.TEST_OFF, None)
            r = subprocess.run([sys.executable, os.path.join(ROOT, "보고서.py"), "월간", "--기준일", "2026-10-31",
                                "--입력", inp, "--출력", out, "--pdf", "안함"], capture_output=True, text=True, env=env, cwd=ROOT)
            self.assertIn("대표·팀장 보고를 만들지 않습니다", r.stdout + r.stderr)
            ceo = open(os.path.join(out, "2026-10-31_월간_대표보고.html"), encoding="utf-8").read()
            self.assertIn("만들지 않았습니다", ceo)
            self.assertNotIn("여유 자금", ceo)
            mg = open(os.path.join(out, "2026-10-31_월간_경영관리보고.html"), encoding="utf-8").read()
            self.assertIn("class='gate'", mg)
            team = [n for n in os.listdir(os.path.join(out, "팀장용"))] if os.path.isdir(os.path.join(out, "팀장용")) else []
            for n in team:
                self.assertIn("만들지 않았습니다", open(os.path.join(out, "팀장용", n), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
