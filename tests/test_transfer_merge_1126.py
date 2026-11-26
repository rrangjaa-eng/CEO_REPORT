"""2026-11-26 사용자: 이체 파일이 '고른 거래처만 합침'인데 모든 거래처를 합쳐 냈다.
transfer.pick 이 창의 주간 출금 목록 합침 설정을 보지 않고 같은 거래처는 늘 한 줄로 합쳤다 → 같은 설정을 따른다. 가상 자료만."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import app, transfer  # noqa: E402

D = dt.date(2026, 11, 27)


def ev(amount, desc, code, day=D):
    return {"date": day, "io": "out", "amount": amount, "desc": desc, "vendor_code": code, "cat": "외주용역비",
            "source": "자금계획서", "project": "", "firm": True, "basis": ""}


def acc(code, name, number, holder):
    return {"거래처코드": code, "거래처": name, "은행": "신한은행", "계좌번호": number, "예금주": holder}


ACC = {"#101": [acc("101", "가상무대", "100000000001", "가상무대")],
       "#102": [acc("102", "가상조명", "100000000002", "가상조명")],
       "#147": [acc("147", "사업소득", "100000000011", "가갑"), acc("147", "사업소득", "100000000012", "나을")]}
EVENTS = [ev(3_000_000, "가상무대", "101"), ev(2_000_000, "(주)가상무대", "101", D - dt.timedelta(days=2)),
          ev(1_500_000, "가상조명", "102"), ev(500_000, "가상조명", "102"),
          ev(920_000, "사업소득", "147"), ev(96_700, "사업소득", "147")]
START, END = D - dt.timedelta(days=6), D


def amounts(rows):
    return sorted(int(r[3]) for r in rows)


class TestMergeSetting(unittest.TestCase):
    def build(self, merge, splits=None):
        multi = []
        rows, blocked, _ = transfer.build(EVENTS, ACC, START, END, splits, multi, {}, merge)
        return rows, blocked, multi

    def test_each_row_when_not_merging(self):
        rows, _, multi = self.build(("건별", []))
        self.assertEqual(amounts(rows), [500_000, 1_500_000, 2_000_000, 3_000_000])
        self.assertEqual(multi[0]["amount"], 1_016_700)   # 예금주가 여럿인 곳은 설정과 관계없이 합쳐 예금주별로 묻는다

    def test_only_picked_vendor_merged(self):
        rows, _, _ = self.build(("고른곳만", ["가상조명"]))
        self.assertEqual(amounts(rows), [2_000_000, 2_000_000, 3_000_000])   # 가상조명만 2,000,000 한 줄, 가상무대는 건별

    def test_picked_name_matches_like_report(self):
        rows, _, _ = self.build(("고른곳만", ["㈜가상무대"]))   # 출금 목록과 같은 이름 맞추기 (㈜·(주) 떼고)
        self.assertEqual(amounts(rows), [500_000, 1_500_000, 5_000_000])

    def test_merge_all(self):
        rows, _, _ = self.build(("모두", []))
        self.assertEqual(amounts(rows), [2_000_000, 5_000_000])

    def test_none_keeps_old_behaviour(self):
        rows, _, _ = self.build(None)
        self.assertEqual(amounts(rows), [2_000_000, 5_000_000])

    def test_multi_holder_split_still_works_in_each_row_mode(self):
        rows, blocked, multi = self.build(("건별", []), splits={"#147": {"가갑": 920_000, "나을": 96_700}})
        self.assertEqual(multi, [])
        self.assertIn(920_000, amounts(rows))
        self.assertIn(96_700, amounts(rows))
        self.assertEqual(blocked, [])

    def test_row_key_never_collides_with_code(self):
        """건별 열쇠가 '#코드' 열쇠와 겹치면 다른 거래처 지급이 합쳐진다 (지급 147번째 줄과 코드 147)."""
        evs = [ev(1, "가상%d" % i, "9%03d" % i) for i in range(150)] + [ev(920_000, "사업소득", "147"), ev(96_700, "사업소득", "147")]
        picked, _ = transfer.pick(evs, START, END, None, transfer.merge_key(("건별", []), ACC))
        self.assertEqual(sorted(ln["amount"] for _, ln in picked)[-1], 1_016_700)
        self.assertEqual(len(picked), 151)


class TestSameHolderSeparate(unittest.TestCase):
    """사용자 2026-11-26: 예금주는 하나여도 금액은 나눠 들어가야 할 때가 있다 (이번 주 최혜진 145,050 + 100,000 이 245,050 한 줄로 나감)."""
    def test_list_plan_keeps_each_line(self):
        evs = [ev(145_050, "사업소득", "147"), ev(100_000, "사업소득", "147"), ev(100_000, "사업소득", "147")]
        plan = {"#147": [("가갑", 145_050), ("가갑", 100_000), ("나을", 100_000)]}
        rows, blocked, _ = transfer.build(evs, ACC, START, END, plan, [], {}, ("건별", []))
        self.assertEqual(blocked, [])
        self.assertEqual(sorted((r[2], int(r[3])) for r in rows), [("가갑", 100_000), ("가갑", 145_050), ("나을", 100_000)])

    def test_unknown_holder_or_wrong_total_asks_again(self):
        evs = [ev(145_050, "사업소득", "147"), ev(100_000, "사업소득", "147")]
        for plan in ([("없는사람", 145_050), ("가갑", 100_000)], [("가갑", 145_050)]):
            multi = []
            rows, blocked, _ = transfer.build(evs, ACC, START, END, {"#147": plan}, multi, {}, ("건별", []))
            self.assertEqual(rows, [])
            self.assertEqual(multi[0]["parts"], [145_050, 100_000])


class TestReadSetting(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.P = type("P", (), {"input": self.d})()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_same_meaning_as_window(self):
        self.assertEqual(transfer.merge_setting(self.d), ("건별", []))   # 파일 없음 = 건별 (창 기본값)
        app.save_merge(self.P, "고른곳만", "가상조명, 가상무대")
        self.assertEqual(transfer.merge_setting(self.d), ("고른곳만", ["가상조명", "가상무대"]))
        app.save_merge(self.P, "고른곳만", "")
        self.assertEqual(transfer.merge_setting(self.d), ("건별", []))   # 0곳 = 합치지 않음
        app.save_merge(self.P, "거래처별", "가상조명")
        self.assertEqual(transfer.merge_setting(self.d), ("모두", []))   # 모두 합침은 고른 목록을 안 씀
        app.save_merge(self.P, "건별", "가상조명")   # 출금 목록은 건별이어도 고른 곳이 저장돼 있으면 이체는 그곳만 합침 (결정 카드 권장안)
        self.assertEqual(transfer.merge_setting(self.d), ("고른곳만", ["가상조명"]))
        app.save_merge(self.P, "건별", "")
        self.assertEqual(transfer.merge_setting(self.d), ("건별", []))


if __name__ == "__main__":
    unittest.main()
