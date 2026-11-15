"""크롬 확장 '대표보고 위하고 수집'이 저장한 분개장 .json 도 읽는다 (2026-11-05). 합성 자료만 쓴다."""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import app, wehago  # noqa: E402
from test_wehago import FAKE_JOURNAL, write_fake_books  # noqa: E402
from test_journal_xls import keyed  # noqa: E402

COLS = ["da_date", "no_acct", "nm_yuh", "nm_gubun_bungae", "cd_acctit", "nm_acctit", "mn_bungae1", "mn_bungae2",
        "nm_trade", "cd_trade", "nm_remark", "nm_project", "nm_dept", "nm_emp", "dt_insert", "sq_acttax2"]


def auto_json(journal=FAKE_JOURNAL, start="20260101", end="20261031", dept="", emp="", project=""):
    rows = []
    for i, r in enumerate(journal):
        d = dt.date(1899, 12, 30) + dt.timedelta(days=int(r[0]))
        debit = int(float(r[5])) if r[5] not in (None, "") else 0
        credit = int(float(r[6])) if r[6] not in (None, "") else 0
        rows.append([d.strftime("%Y%m%d"), str(r[1]).zfill(5), "일반전표", "차변" if debit else "대변", r[3], r[4],
                     debit, credit, r[7], r[8], r[9], project, dept, emp, "2026-11-05T10:00:00.000", i + 1])
    return {"종류": "분개장", "형식": 1, "수집시각": "2026-11-05 10:00:00", "회사": "가상회사",
            "기간": {"start_date": start, "end_date": end, "gisu": "2"}, "전표수": 0, "줄수": len(rows), "열": COLS, "줄": rows}


def write_json(folder, name, doc):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


class TestJournalJson(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_json_reads_like_xlsx(self):
        ref = os.path.join(self.dir, "ref")
        write_fake_books(ref)
        want = wehago.load_books(ref, dt.date(2026, 11, 2), None)
        got_dir = os.path.join(self.dir, "got")
        write_fake_books(got_dir, drop=("분개장",))
        write_json(got_dir, "261105 분개장 자동수집.json", auto_json())
        got = wehago.load_books(got_dir, dt.date(2026, 11, 5), None)
        self.assertEqual(got.state, "ok", got.reason)
        self.assertEqual(keyed(got.journal), keyed(want.journal))
        self.assertEqual(got.files["분개장"]["name"], "261105 분개장 자동수집.json")
        self.assertEqual(got.files["분개장"]["file_date"], dt.date(2026, 11, 5))

    def test_codes_stripped_from_dept_emp_project(self):
        rows = wehago.read_journal_json(self._write(auto_json(dept="[0002]기획1팀", emp="[0007]가나다",
                                                              project="[00001][26222] 가상행사")))
        head = rows[0]
        first = dict(zip(head, rows[1]))
        self.assertEqual(first["부서명"], "기획1팀")
        self.assertEqual(first["사원명"], "가나다")
        self.assertEqual(first["프로젝트명"], "[26222] 가상행사")
        self.assertEqual(rows.period, (dt.date(2026, 1, 1), dt.date(2026, 10, 31)))

    def test_newer_json_beats_older_xls_name(self):
        write_fake_books(self.dir, stamp="20261013")
        write_json(self.dir, "261105 분개장 자동수집.json", auto_json())
        books = wehago.load_books(self.dir, dt.date(2026, 11, 5), None)
        self.assertEqual(books.files["분개장"]["name"], "261105 분개장 자동수집.json")

    def test_bad_json_is_reported_not_crash(self):
        with open(os.path.join(self.dir, "261105 분개장 자동수집.json"), "w", encoding="utf-8") as f:
            f.write("{깨진")
        write_fake_books(self.dir, drop=("분개장",))
        books = wehago.load_books(self.dir, dt.date(2026, 11, 5), None)
        self.assertNotEqual(books.state, "ok")

    def test_import_auto_copies_new_files_only(self):
        dl = os.path.join(self.dir, "dl")
        write_json(os.path.join(dl, app.AUTO_DIR), "261105 분개장 자동수집.json", auto_json())
        with open(os.path.join(dl, app.AUTO_DIR, "다른파일.json"), "w") as f:
            f.write("{}")
        paths = app.Paths(os.path.join(self.dir, "prog"))
        said = []
        self.assertEqual(app.import_auto(paths, said.append, dirs=[dl]), 1)
        self.assertTrue(os.path.exists(os.path.join(paths.wehago, "261105 분개장 자동수집.json")))
        self.assertFalse(os.path.exists(os.path.join(paths.wehago, "다른파일.json")))
        self.assertEqual(app.import_auto(paths, said.append, dirs=[dl]), 0)   # 이미 같은 것

    def test_chrome_download_dirs_reads_preferences(self):
        local = os.path.join(self.dir, "local")
        prof = os.path.join(local, "Google", "Chrome", "User Data", "Default")
        os.makedirs(prof)
        with open(os.path.join(prof, "Preferences"), "w", encoding="utf-8") as f:
            json.dump({"download": {"default_directory": "F:\\ERP\\다운로드"}}, f)
        dirs = app.chrome_download_dirs({"LOCALAPPDATA": local, "USERPROFILE": "C:\\Users\\u"})
        self.assertEqual(dirs[0], "F:\\ERP\\다운로드")
        self.assertEqual(dirs[1], os.path.join("C:\\Users\\u", "Downloads"))

    def _write(self, doc):
        p = os.path.join(self.dir, "x 분개장 자동수집.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        return p


if __name__ == "__main__":
    unittest.main()
