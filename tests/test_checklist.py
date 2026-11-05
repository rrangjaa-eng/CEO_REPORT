"""확인할 것 화면·결정 저장·통장 잔액 대조·홈택스 대조·중복 의심 자동 판단·입력 백업 (사용자 2026-11-05)."""
import csv
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import app, checklist, hometax, review_checks, transfer  # noqa: E402
from ceo_report.render import _group_small  # noqa: E402

D = dt.date


def ln(day, no, code, debit=None, credit=None, vendor="가상상사", memo="물품", sort="매입전표", project=""):
    return {"date": day, "no": no, "account_code": code, "debit": debit, "credit": credit, "vendor": vendor,
            "vendor_norm": vendor, "memo": memo, "sort": sort, "project_name": project}


def buy(day, no, amt, memo="물품", project="", vendor="가상상사"):
    vat = amt // 11
    return [ln(day, no, "63300", debit=amt - vat, memo=memo, project=project, vendor=vendor),
            ln(day, no, "13500", debit=vat, memo=memo, project=project, vendor=vendor),
            ln(day, no, "25300", credit=amt, memo=memo, project=project, vendor=vendor)]


class TestDuplicates(unittest.TestCase):
    def test_suspect_when_same_memo_and_not_settled_twice(self):
        J = buy(D(2026, 10, 1), "50001", 1100000) + buy(D(2026, 10, 1), "50002", 1100000)
        J += [ln(D(2026, 10, 20), "00010", "25300", debit=1100000)]   # 한 번만 지급
        cls = review_checks.classify_duplicates(J)
        self.assertEqual(len(cls), 1)
        self.assertFalse(cls[0][4])
        self.assertIn("이중 입력 가능성", cls[0][3])
        self.assertEqual(len(review_checks.duplicate_items(J)), 1)

    def test_cancel_and_reissue_is_normal(self):
        J = buy(D(2026, 10, 28), "50002", 1155000) + buy(D(2026, 10, 28), "50004", 1155000)
        J += [ln(D(2026, 10, 28), "50003", "25300", credit=-1155000)]
        cls = review_checks.classify_duplicates(J)
        self.assertTrue(cls[0][4])
        self.assertIn("취소", cls[0][3])
        self.assertEqual(review_checks.duplicate_items(J), [])

    def test_different_memo_or_settled_each_is_normal(self):
        J = buy(D(2026, 10, 1), "50001", 1100000, memo="가") + buy(D(2026, 10, 1), "50002", 1100000, memo="나")
        self.assertTrue(review_checks.classify_duplicates(J)[0][4])
        J = buy(D(2026, 10, 1), "50001", 1100000) + buy(D(2026, 10, 1), "50002", 1100000)
        J += [ln(D(2026, 10, 20), "00010", "25300", debit=1100000), ln(D(2026, 11, 20), "00011", "25300", debit=1100000)]
        self.assertTrue(review_checks.classify_duplicates(J)[0][4])
        self.assertIn("정상으로 본 1묶음", review_checks.duplicate_lines(J)[0])


class TestDecisions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_save_change_and_clear(self):
        checklist.save_decision(self.tmp, "중복|a", "정상 (별개 거래)", "메모", "내용")
        checklist.save_decision(self.tmp, "중복|b", "이중 입력 — 위하고에서 고칠 것")
        d = checklist.read_decisions(self.tmp)
        self.assertEqual(d["중복|a"]["메모"], "메모")
        checklist.save_decision(self.tmp, "중복|a", "")
        self.assertEqual(list(checklist.read_decisions(self.tmp)), ["중복|b"])

    def test_gather_states_and_render(self):
        items = [{"id": "x1", "kind": "중복 의심 전표", "date": "2026-10-01", "amount": 5, "vendor": "<가상>", "title": "t",
                  "detail": "d", "choices": ["이중 입력 — 위하고에서 고칠 것", "정상 (별개 거래)"]},
                 {"id": "x2", "kind": "카드 전표", "date": "", "amount": None, "vendor": "", "title": "t2", "detail": "",
                  "choices": ["확인함"]}]
        checklist.save_convert_items(self.tmp, items)
        checklist.save_decision(self.tmp, "x1", "이중 입력 — 위하고에서 고칠 것")
        checklist.save_decision(self.tmp, "x2", "확인함")
        G = checklist.gather(self.tmp, self.tmp, D(2026, 10, 31))
        st = dict((it["id"], it["state"]) for it in G["items"])
        self.assertEqual((st["x1"], st["x2"]), ("fix", "done"))
        page = checklist.render(G, "KEY")
        self.assertIn("&lt;가상&gt;", page)
        self.assertNotIn("<가상>", page)
        self.assertIn("결정한 것도 보기", page)
        self.assertIn("&lt;○○○", checklist.render(G, "KEY", mask=True))

    def test_session_needs_key(self):
        checklist.save_convert_items(self.tmp, [{"id": "x1", "kind": "카드 전표", "date": "", "amount": None, "vendor": "",
                                                 "title": "t", "detail": "", "choices": ["확인함"]}])
        s = checklist.Session(self.tmp, self.tmp, D(2026, 10, 31))
        url = s.start()
        self.addCleanup(s.stop)
        with urllib.request.urlopen(url) as r:
            self.assertIn("확인할 것", r.read().decode("utf-8"))
        base = url.rsplit("/", 1)[0]
        body = json.dumps({"id": "x1", "choice": "확인함"}).encode("utf-8")
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(urllib.request.Request(base + "/decide?k=bad", data=body))
        with urllib.request.urlopen(urllib.request.Request(base + "/decide?k=" + s.key, data=body)) as r:
            self.assertEqual(json.loads(r.read().decode("utf-8"))["state"], "done")
        self.assertEqual(checklist.read_decisions(self.tmp)["x1"]["결정"], "확인함")


class TestBank(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        with open(os.path.join(self.tmp, "장부잔액.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["기준일", "계좌명", "은행", "잔액"])
            w.writerow(["2026-10-31", "가", "", "1000"])
            w.writerow(["2026-10-31", "나", "", "500"])
        with open(os.path.join(self.tmp, "장부입출금.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["일자", "계좌명", "입출금", "금액", "분류", "프로젝트번호", "거래처", "적요"])
            w.writerow(["2026-10-15", "가", "입금", "9999", "", "", "", ""])
            w.writerow(["2026-11-02", "가", "출금", "300", "", "", "", ""])
            w.writerow(["2026-11-03", "가", "입금", "100", "", "", "", ""])

    def test_book_balance_from_snapshot_plus_moves(self):
        self.assertEqual(checklist.book_balance(self.tmp, D(2026, 11, 2))[0], 1200)
        self.assertEqual(checklist.book_balance(self.tmp, D(2026, 11, 3))[0], 1300)

    def test_bank_item_only_when_different_and_book_has_the_day(self):
        checklist.save_bank(self.tmp, "2026-11-02", "1,200")
        self.assertEqual(checklist.bank_items(self.tmp), [])
        self.assertIn("일치", checklist.bank_line(self.tmp, D(2026, 11, 2)))
        checklist.save_bank(self.tmp, "2026-11-03", "1,250")
        items = checklist.bank_items(self.tmp)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["amount"], -50)
        checklist.save_bank(self.tmp, "2026-11-10", "1")   # 장부가 아직 그날까지 없음
        self.assertEqual(len(checklist.bank_items(self.tmp)), 1)
        with self.assertRaises(ValueError):
            checklist.save_bank(self.tmp, "11월", "1")


class TestHometax(unittest.TestCase):
    def rows(self, sup_same):
        head = ["작성일자", "승인번호", "발급일자", "전송일자", "공급자사업자등록번호", "종사업장번호", "상호", "대표자명",
                "공급받는자사업자등록번호", "종사업장번호", "상호", "대표자명", "합계금액", "공급가액", "세액"]
        out = [["전자(세금)계산서 목록"], [], head]
        for i, (day, total, other) in enumerate((("2026-10-01", 1100, "가상갑"), ("2026-10-05", 2200, "가상을"))):
            us, them = ("111", "우리"), ("2%d" % i, other)
            sup, bu = (us, them) if sup_same else (them, us)
            out.append([day, "2026100%d-0001" % i, day, day, sup[0], "", sup[1], "", bu[0], "", bu[1], "", total, total // 11 * 10,
                        total // 11])
        return out

    def test_direction_and_match(self):
        side, rows = hometax.parse_rows(self.rows(True))
        self.assertEqual(side, "매출")
        self.assertEqual(rows[0]["vendor"], "가상갑")
        side, rows = hometax.parse_rows(self.rows(False))
        self.assertEqual(side, "매입")
        books = [{"date": D(2026, 10, 3), "no": "1", "total": 1100, "vendor_norm": "가상갑", "vendor": "가상갑"}]
        only_ht, only_books, ok = hometax._match(rows, books)
        self.assertEqual((ok, [h["total"] for h in only_ht]), (1, [2200]))

    def test_no_folder_is_quiet(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertEqual(hometax.compare(tmp, []), {"notes": [], "items": []})


class TestTransferMissing(unittest.TestCase):
    def test_missing_accounts(self):
        ev = lambda day, amt, name, code: {"io": "out", "date": day, "amount": amt, "desc": name, "vendor_code": code, "cat": "미지급금",
                                           "firm": True, "source": "자금계획서"}
        accounts = {transfer.code_key("100"): [{"거래처코드": "100", "거래처": "있음", "은행": "신한", "계좌번호": "110", "예금주": "가"}]}
        m = transfer.missing_accounts([ev(D(2026, 11, 3), 500, "있음", "100"), ev(D(2026, 11, 4), 700, "없음", "200")],
                                      accounts, D(2026, 11, 1), D(2026, 11, 7))
        self.assertEqual([(x["vendor"], x["amount"]) for x in m], [("없음", 700)])


class TestBackup(unittest.TestCase):
    def test_keeps_ten_and_skips_old_and_credentials(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        P = app.Paths(tmp)
        os.makedirs(os.path.join(P.input, "이전", "x"))
        for n in ("손익.csv", "인트라넷계정.dat"):
            with open(os.path.join(P.input, n), "w") as f:
                f.write("1")
        for k in range(12):
            app.backup_input(P, now=dt.datetime(2026, 11, 1, 9, 0, k))
        base = os.path.join(tmp, app.BACKUP_DIR)
        kept = sorted(os.listdir(base))
        self.assertEqual(len(kept), 10)
        self.assertEqual(kept[0], "20261101_090002")
        self.assertEqual(sorted(os.listdir(os.path.join(base, kept[-1]))), ["손익.csv"])


class TestGroupSmall(unittest.TestCase):
    def test_welfare_rows_become_one(self):
        rows = [{"date": D(2026, 11, 6), "amount": 100000, "firm": True, "desc": "직원%d" % i, "cat": "복리후생비", "project": ""}
                for i in range(4)] + [{"date": D(2026, 11, 6), "amount": 5, "firm": True, "desc": "가", "cat": "미지급금", "project": ""}]
        out = _group_small(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["amount"], 400000)
        self.assertEqual(out[0]["desc"], "직원 4명")
        self.assertEqual(len(_group_small(rows[:2] + rows[4:])), 3)


if __name__ == "__main__":
    unittest.main()


class TestPayableTrace(unittest.TestCase):
    def test_cancel_and_reissue_is_explained(self):
        import datetime as dt
        from ceo_report import review_checks
        d = dt.date(2026, 10, 28)
        ln = lambda no, cr: {"date": d, "no": no, "account_code": "25300", "vendor_code": "00604", "credit": cr, "debit": None}
        tr = review_checks.payable_trace([ln("50002", 1155000), ln("50003", -1155000), ln("50004", 1155000)], ("25300",))
        e = tr["604"]
        self.assertEqual(e["balance"], 1155000)
        self.assertIn("50003", e["text"])
        self.assertIn("다시 발행", e["text"])
        self.assertIn("장부는 맞음", e["text"])

    def test_no_cancel_no_text(self):
        import datetime as dt
        from ceo_report import review_checks
        tr = review_checks.payable_trace([{"date": dt.date(2026, 10, 1), "no": "1", "account_code": "25300",
                                           "vendor_code": "7", "credit": 500, "debit": None}], ("25300",))
        self.assertEqual(tr["7"]["text"], "")

    def test_vendor_label(self):
        from ceo_report import checklist
        self.assertEqual(checklist.vendor_label("가나상사", "604"), "가나상사 [604]")
        self.assertEqual(checklist.vendor_label("가나상사", ""), "가나상사")
        self.assertEqual(checklist.vendor_label("", "604"), "[604]")
