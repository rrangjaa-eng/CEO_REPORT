"""자료 대조 (reconcile.py, 사용자 2026-11-14 결정). 실제 위하고 응답 모양(11/14 PC에서 칸 이름만 확인)으로 만든 가짜 자료."""
import csv
import datetime as dt
import json
import os
import tempfile
import unittest

from ceo_report import reconcile as RC

D = dt.date


def ln(day, code, debit=0, credit=0, vcode="", account="", project="", memo=""):
    return {"date": day, "account_code": code, "account": account, "debit": debit, "credit": credit, "vendor_code": vcode,
            "project_name": project, "memo": memo}


class Books:
    state = "ok"

    def __init__(self, journal):
        self.journal = journal


def save(folder, name, doc):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def raw(code, when, data_by_path, year=2026):
    return {"종류": "결산원본", "형식": 1, "수집시각": when, "연도": year, "화면": code, "화면코드": code, "자동": True,
            "응답": [{"path": p, "data": d} for p, d in data_by_path.items()]}


def tb_rows(bal):
    """{계정코드: 차변 − 대변} -> 시산표 main_rows (llp 차변 잔액, rrp 대변 잔액)."""
    out = [{"cd_acctit": None, "nm_acctitpr": "<자산>", "llp": 0, "rrp": 0}]
    for c, v in bal.items():
        out.append({"cd_acctit": c, "nm_acctitpr": c, "llp": max(v, 0), "rrp": max(-v, 0), "l_prc": 0, "r_prc": 0})
    return {"bigclass_rows": [], "main_rows": out}


JCOLS = ["da_date", "no_acct", "nm_yuh", "nm_gubun_bungae", "cd_acctit", "nm_acctit", "mn_bungae1", "mn_bungae2", "nm_trade",
         "cd_trade", "nm_remark", "nm_project", "nm_dept", "nm_emp", "dt_insert", "sq_acttax2"]


def jfile(when, lines):
    return {"종류": "분개장", "형식": 1, "수집시각": when, "기간": {"start_date": "20260101", "end_date": "20261231"},
            "열": JCOLS, "줄": lines}


def jline(day, acct, d, c, sq, ins="20261113120000"):
    return [day, "1", "일반", "차변" if d else "대변", acct, "", d, c, "", "", "", "", "", "", ins, sq]


JOURNAL = [ln(D(2026, 1, 2), "10300", 500_000_000), ln(D(2026, 1, 2), "33100", 0, 500_000_000),
           ln(D(2026, 11, 10), "13101", 5_820_080), ln(D(2026, 11, 10), "10300", 0, 5_820_080),
           ln(D(2026, 11, 12), "82100", 35_618_500), ln(D(2026, 11, 12), "25300", 0, 35_618_500),
           ln(D(2026, 11, 13), "25300", 35_618_500), ln(D(2026, 11, 13), "10300", 0, 35_618_500),
           ln(D(2026, 5, 11), "10300", 300_000_000, vcode="0000001107"), ln(D(2026, 5, 11), "29300", 0, 300_000_000, vcode="0000001107")]


class TestBalances(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()

    def _tb(self, when, bal):
        save(self.t, "261113 대조_합계잔액시산표 자동수집.json", raw("SACL0104", when, {"/smarta/sacl0104/account/": tb_rows(bal)}))

    def test_same_time_equal_and_subaccount_grouped(self):
        save(self.t, "261113 분개장 자동수집.json", jfile("2026-11-13 14:00:00", []))
        b = RC.book_balances(JOURNAL)
        # 위하고는 13101 을 13100 에 합쳐 보인다 → 앞 세 자리로 묶으면 같음
        self._tb("2026-11-13 14:05:00", {"10300": b["103"] + b.get("131", 0) * 0, "13100": 5_820_080, "25300": 0,
                                          "29300": -300_000_000, "33100": -500_000_000})
        rows = RC.balances_rows(JOURNAL, RC.raw_files(self.t), RC.journal_files(self.t)[0][0])
        self.assertEqual([r["판정"] for r in rows], ["같음"], rows)

    def test_different_time_is_only_reference(self):
        # 11/13 실제: 시산표(재무상태표)를 받은 뒤 지급 전표가 들어가 통장·미지급금이 3,561만 달라 보임 → 경고 안 함
        save(self.t, "261113 분개장 자동수집.json", jfile("2026-11-13 14:00:00", []))
        b = RC.book_balances([x for x in JOURNAL if x["date"] < D(2026, 11, 13)])
        self._tb("2026-11-13 12:10:00", {"10300": b["103"], "13100": b["131"], "25300": b["253"], "29300": b["293"],
                                          "33100": b["331"]})
        rows = RC.balances_rows(JOURNAL, RC.raw_files(self.t), RC.journal_files(self.t)[0][0])
        bank = [r for r in rows if r["항목"] == "보통예금"][0]
        self.assertEqual(bank["판정"], "참고")
        self.assertEqual(bank["대표경고"], "")

    def test_same_time_big_diff_warns_ceo(self):
        save(self.t, "261113 분개장 자동수집.json", jfile("2026-11-13 14:00:00", []))
        b = RC.book_balances(JOURNAL)
        self._tb("2026-11-13 14:01:00", {"10300": b["103"] + 20_000_000, "13100": b["131"], "29300": b["293"], "33100": b["331"]})
        rows = RC.balances_rows(JOURNAL, RC.raw_files(self.t), RC.journal_files(self.t)[0][0])
        bank = [r for r in rows if r["항목"] == "보통예금"][0]
        self.assertEqual((bank["판정"], bank["대표경고"], bank["차이"]), ("다름", "예", "-20000000"))

    def test_for_report_and_check_items(self):
        with open(os.path.join(self.t, RC.FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, RC.KEYS)
            w.writeheader()
            w.writerow(RC._row("잔액", "보통예금", "합계잔액시산표", 120, 100, "", "다름", "x", "예"))
            w.writerow(RC._row("잔액", "단기차입금", "합계잔액시산표", -50, -30, "", "다름", "x", "예"))
            w.writerow(RC._row("잔액", "장기차입금", "합계잔액시산표", -50, -40, "", "다름", "x", "예"))
            w.writerow(RC._row("잔액", "선급금", "합계잔액시산표", 1, 1, "", "같음"))
        recon, rows = RC.for_report(self.t)
        self.assertEqual(recon, [{"what": "통장", "diff": -20}, {"what": "차입금", "diff": 30}])
        self.assertEqual(len(RC.check_items(self.t)), 3)
        html = RC.render(rows, lambda s: str(s or ""))
        self.assertIn("자료 대조", html)


class TestBalanceSheet(unittest.TestCase):
    def test_closed_year_compares_year_end(self):
        t = tempfile.mkdtemp()
        j = [ln(D(2025, 3, 1), "10300", 100), ln(D(2025, 3, 1), "25300", 0, 100), ln(D(2026, 2, 1), "10300", 5),
             ln(D(2026, 2, 1), "25300", 0, 5)]
        main = {"main": [{"cd_acctit": "10300", "nm_acctit": "보통예금", "mn_bungae": 100},
                         {"cd_acctit": "25300", "nm_acctit": "미지급금", "mn_bungae_right": 100},
                         {"cd_acctit": "", "nm_acctit": "자산총계", "mn_bungae": 100}]}
        save(t, "261113 결산_재무상태표_2025 자동수집.json", raw("SACL0105", "2026-11-13 10:00:00", {"/smarta/sacl0105/main/": main}, 2025))
        save(t, "261113 분개장 자동수집.json", jfile("2026-11-13 14:00:00", []))
        rows = RC.balances_rows(j, RC.raw_files(t), RC.journal_files(t)[0][0])
        self.assertEqual([(r["판정"], r["비교자료"]) for r in rows], [("같음", "재무상태표 2025")])


class TestJournal(unittest.TestCase):
    def test_late_rows_and_last_bank(self):
        t = tempfile.mkdtemp()
        old = [jline("20261001", "10300", 1000, 0, 1), jline("20261001", "40100", 0, 1000, 2)]
        new = old[:1] + [jline("20261001", "40100", 0, 1500, 2), jline("20261020", "82100", 7000, 0, 3),
                         jline("20261020", "25300", 0, 7000, 4), jline("20261112", "10300", 0, 10, 5)]
        save(t, "261110 분개장 자동수집.json", jfile("2026-11-10 09:00:00", old))
        save(t, "261113 분개장 자동수집.json", jfile("2026-11-13 14:00:00", new))
        rows = RC.journal_rows(RC.journal_files(t), D(2026, 11, 13))
        items = [r["항목"] for r in rows]
        self.assertIn("2026-10 전표 2줄", items)
        self.assertIn("지워진 줄 0 · 바뀐 줄 1", items)
        bank = [r for r in rows if r["항목"].startswith("통장")][0]
        self.assertEqual(bank["판정"], "같음")
        late = RC.journal_rows(RC.journal_files(t), D(2026, 11, 30))
        self.assertEqual([r for r in late if r["항목"].startswith("통장")][0]["판정"], "다름")


class TestLoans(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        g = [{"ty_refund2": "일시", "da_expire": "20260417", "mn_janac": 200000000, "no_loan": "1", "nm_trade": "신한대출_기술보증기금_123456789012",
              "da_floan": "20250417", "mn_loan_sum": 0, "ty_funduse2": "운영", "cd_trade": "0000000256", "mn_prin": 200000000},
             {"ty_refund2": "분할(원리금)", "da_expire": "20300921", "mn_janac": 70000000, "nm_trade": "하나캐피탈", "da_floan": "20250924",
              "ty_funduse2": "차량운반구", "cd_trade": "0000000679", "mn_prin": 80330000},
             {"ty_refund2": "일시", "da_expire": "20270421", "mn_janac": 300000000, "nm_trade": "신한대출_기술보증기금_987654321098",
              "da_floan": "20260511", "ty_funduse2": "운영", "cd_trade": "0000001107", "mn_prin": 300000000}]
        save(self.t, "261114 대조_차입금현황 자동수집.json",
             raw("SAFM0109", "2026-11-14 10:00:00", {"/smarta/safm0109/": {"group01": g, "group02": {}}}))
        self.j = [ln(D(2025, 4, 17), "29300", 0, 200_000_000, "00256"), ln(D(2025, 9, 24), "29300", 0, 80_330_000, "00679"),
                  ln(D(2026, 10, 24), "29300", 15_580_000, 0, "00679"), ln(D(2026, 5, 11), "29300", 0, 300_000_000, "01107")]

    def test_expired_without_override_asks_new_date(self):
        with open(os.path.join(self.t, RC.MATURITY_FILE), "w", encoding="utf-8-sig") as f:
            f.write(",".join(RC.MATURITY_KEYS) + "\n")   # 사용자가 기본 줄을 지운 파일
        loans, rows = RC.loan_rows(self.j, RC.raw_files(self.t), self.t, D(2026, 11, 14))
        shin = [l for l in loans if l["거래처코드"] == "256"][0]
        self.assertEqual((shin["만기일"], shin["만기근거"], shin["매년연장"], shin["계정코드"]), ("2026-04-17", "차입금현황", "", "29300"))
        self.assertNotIn("1234", shin["차입처"])   # 이름 끝 계좌번호는 뺀다
        self.assertTrue(any(r["항목"].startswith("신한") and r["판정"] == "다름" for r in rows))
        hana = [r for r in rows if r["항목"] == "하나캐피탈"][0]   # 위하고 상환 기록 미갱신: 참고만, 잔액은 장부
        self.assertEqual((hana["판정"], hana["장부값"]), ("참고", "64750000"))

    def test_default_override_yearly_extension(self):
        # 파일이 없으면 사용자가 알려 준 기본값 (11/14): 기보 2건 매년 연장
        loans, rows = RC.loan_rows(self.j, RC.raw_files(self.t), self.t, D(2026, 11, 14))
        by = {l["거래처코드"]: l for l in loans}
        self.assertEqual((by["256"]["만기일"], by["256"]["만기근거"], by["256"]["매년연장"]), ("2027-04-17", "직접 입력", "예"))
        self.assertEqual((by["1107"]["만기일"], by["1107"]["만기근거"], by["1107"]["매년연장"]), ("2027-04-21", "차입금현황", "예"))
        self.assertEqual((by["679"]["상환방식"], by["679"]["월상환액"], by["679"]["매년연장"]), ("분할", "", ""))
        self.assertFalse(any(r["판정"] == "다름" for r in rows))

    def test_build_tables_writes_loan_csv(self):
        tabs = RC.build_tables(Books(self.j), self.t, self.t, D(2026, 11, 14))
        names = {x.name: x for x in tabs}
        self.assertTrue(names["차입금.csv"].written)
        self.assertEqual(names["차입금.csv"].columns, RC.LOAN_KEYS)
        self.assertFalse(names["카드사용.csv"].written)


class TestIntranetAndEtax(unittest.TestCase):
    def test_intranet_invoice_column(self):
        j = [ln(D(2026, 3, 1), "41200", 0, 10_000_000, project="[26001] 봄 행사"),
             ln(D(2026, 3, 1), "41200", 0, 5_000_000, project="[26002] 여름 행사")]
        P = [{"행사명": "[26001] 봄 행사", "계산서": "11,000,000"},   # 부가세 포함으로 적음 → 같음
             {"행사명": "[26002] 여름 행사", "계산서": "3,000,000"}, {"행사명": "[26003] 가을", "계산서": ""}]
        rows = RC.intranet_rows(j, P)
        self.assertEqual([r["항목"] for r in rows if r["판정"] == "다름"], ["[26002] 여름 행사", "프로젝트 요약"])

    def test_etax_matches_sales_slips(self):
        t = tempfile.mkdtemp()
        res = {"result1": [{"da_sbook": "20260106", "cd_trade": "0000000101", "mn_mnam": 1000, "mn_vat": 100},
                           {"da_sbook": "20260107", "cd_trade": "0000000102", "mn_mnam": 2000, "mn_vat": 200}], "result2": []}
        save(t, "x.json", raw("SAAC0103", "2026-11-14 10:00:00", {"/smarta/saac0103/jungsang/": res}))
        j = [ln(D(2026, 1, 6), "41200", 0, 1000, "00101")]
        rows = RC.etax_rows(j, RC.raw_files(t))
        self.assertEqual((rows[0]["판정"], rows[0]["비교값"], rows[0]["장부값"]), ("다름", "1", "2"))

    def test_card_table(self):
        t = tempfile.mkdtemp()
        res = {"data": [{"da_sbook": "20261005", "nm_ctrade": "[00139]신한_5860", "cd_ctrade": "0000000139", "mn_mnam": 1000,
                         "mn_vat": 100, "mn_total": 1100, "ty_jungstat": 1},
                        {"da_sbook": "20261020", "nm_ctrade": "[00139]신한_5860", "cd_ctrade": "0000000139", "mn_mnam": 500,
                         "mn_vat": 50, "mn_total": 550, "ty_jungstat": 5}]}
        d = raw("SAAC0105", "2026-11-14 10:00:00", {"/smarta/saac0105/6/": res}, year=0)
        save(t, "261114 결산_신용카드 자동수집.json", d)
        rows = RC.card_table(RC.raw_files(t))
        self.assertEqual(rows, [{"연월": "2026-10", "카드": "신한_5860", "카드코드": "139", "공급가": "1500", "부가세": "150",
                                 "합계": "1650", "건수": "2", "전표처리": "1·5"}])


if __name__ == "__main__":
    unittest.main()
