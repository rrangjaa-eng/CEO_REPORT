"""2026-11-16 편의성 개선 31건 (결정 카드 ①~④ 답: 높음·중간 전부 / 출금일 지금처럼+표시 / 나눠 셈 / 목록에서 골라 입력).

번호는 편의성 제안 문서의 번호. 운영-03(금요일 출금일)·운영-04(건수 나눔)·운영-05(드문 카드 목록) 규칙의 '확인'도 여기.
모두 가상 자료다 (실제 입력/·수집/ 폴더는 열지 않는다).
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import app, checklist, gate, occasional, transfer, winstate  # noqa: E402

D = dt.date


class TransferCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inp = os.path.join(self.tmp, "입력")
        self.out = os.path.join(self.tmp, "출력")
        self.col = os.path.join(self.tmp, "수집", "위하고")
        self.dl = os.path.join(self.tmp, "Downloads")
        os.makedirs(self.col)
        os.makedirs(os.path.join(self.dl, app.AUTO_DIR))
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), self.inp)
        with open(os.path.join(self.inp, "거래처계좌.csv"), "w", encoding="utf-8-sig") as f:
            f.write("거래처,은행,계좌번호,예금주\n디자인스튜디오,우리은행,1002-000-000003,가상디자인\n")
        self.conv(dt.datetime.now())

    def conv(self, when):
        with open(os.path.join(self.inp, "변환결과.txt"), "w", encoding="utf-8-sig") as f:
            f.write("변환 시각 %s · 기준일 2026-10-31\nWEHAGO 장부: ok\n" % when.strftime("%Y-%m-%d %H:%M:%S"))

    def make(self, **kw):
        lines, result = [], {}
        kw.setdefault("downloads", [self.dl])
        with mock.patch.dict(os.environ, {"CEO_REPORT_TEST_GATE_OFF": "1"}):
            path = transfer.make_file(self.inp, self.out, D(2026, 11, 1), D(2026, 11, 30), lines.append, asof=D(2026, 10, 31),
                                      collect_dir=self.col, result=result, **kw)
        return path, lines, result


class TestItem13DownloadFolderBlocksTransfer(TransferCase):
    def test_new_journal_waiting_in_chrome_downloads_blocks(self):
        """13: 크롬 다운로드 폴더에 받아만 둔 새 분개장도 '변환 뒤 새 자료' — 이미 낸 지급이 다시 들어가지 않게 막는다."""
        self.conv(dt.datetime.now() - dt.timedelta(hours=2))
        p = os.path.join(self.dl, app.AUTO_DIR, "261116 분개장 자동수집.json")
        with open(p, "w") as f:
            f.write("{}")
        path, lines, result = self.make()
        self.assertIsNone(path)
        self.assertTrue(any("다운로드 폴더" in x for x in result["blocked"]), result["blocked"])

    def test_old_download_does_not_block(self):
        p = os.path.join(self.dl, app.AUTO_DIR, "261001 분개장 자동수집.json")
        with open(p, "w") as f:
            f.write("{}")
        t = time.time() - 86400
        os.utime(p, (t, t))
        path, lines, result = self.make()
        self.assertTrue(path, lines)


class TestItem16NoFileWithoutLog(TransferCase):
    def test_log_not_writable_means_no_file(self):
        """16: 이체기록.csv 를 쓰지 못하면 이체 파일을 내보내지 않는다 (다음 주 '같은 계좌·금액' 경고가 빠지지 않게)."""
        os.makedirs(os.path.join(self.inp, transfer.LOG_FILE))   # 쓸 수 없는 기록 파일 (엑셀로 열어 둔 것 대신)
        path, lines, result = self.make()
        self.assertIsNone(path)
        self.assertEqual(transfer._period_files(self.out, D(2026, 11, 1), D(2026, 11, 30)), [])
        self.assertTrue(result.get("log_failed"))
        self.assertTrue(any("이체기록.csv" in x and "닫고" in x for x in lines), lines)


class TestItem11TransferSummary(TransferCase):
    def test_summary_counts_and_repeat_names(self):
        """11: 넣음·못 넣음·중복 의심을 결과로 돌려줘 창의 이체 칸에 남긴다. 중복 의심이 있으면 빨강 + 거래처."""
        p1, _, r1 = self.make(now=dt.datetime(2026, 10, 31, 9, 0, 0))
        s = r1["summary"]
        self.assertEqual((s["n"], s["total"]), (1, sum(int(x[3]) for x in s["rows"])))
        self.assertEqual(s["repeats"], [])
        text, bad = winstate.transfer_summary(r1)
        self.assertIn("넣음 1건", text)
        self.assertFalse(bad)
        p2, _, r2 = self.make(now=dt.datetime(2026, 10, 31, 10, 0, 0))
        self.assertEqual(len(r2["summary"]["repeats"]), 1)
        text, bad = winstate.transfer_summary(r2)
        self.assertTrue(bad)
        self.assertIn("중복 의심 1건", text)
        self.assertIn("가상디자인", text)

    def test_blocked_summary(self):
        text, bad = winstate.transfer_summary({"blocked": ["자금계획서 없음"], "summary": None})
        self.assertTrue(bad)
        self.assertIn("만들지 않음", text)


def _item(i, kind="카드 전표", choices=("확인함",), amount=None, **kw):
    return dict({"id": i, "kind": kind, "date": "", "amount": amount, "vendor": "", "title": "t " + i, "detail": "d", "choices": list(choices)}, **kw)


class ChecklistCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def gather(self):
        return checklist.gather(self.tmp, self.tmp, D(2026, 10, 31))

    def G(self, items):
        """가상 항목만으로 만든 화면 자료 (빈 입력 폴더가 만드는 다른 알림은 빼고)."""
        return {"items": items, "convert_at": "", "counts": checklist.apply_decisions(items, checklist.read_decisions(self.tmp))}

    def mine(self, i):
        return [it for it in self.gather()["items"] if it["id"] == i][0]


class TestRuleOps04SplitCounts(ChecklistCase):
    """운영-04 (결정 카드 ③ '나눠 셈', 편의성 17): '보고 전에 볼 것'과 경영관리 '할 일 기록'을 따로 세고 묶음도 나눈다."""

    def test_report_todos_are_counted_apart(self):
        items = [_item("a"), _item("b"), _item("t1", kind="보고 할 일"), _item("t2", kind="보고 할 일"), _item("t3", kind="보고 할 일")]
        checklist.save_decision(self.tmp, "t3", "처리함")
        G = self.G(items)
        c = G["counts"]
        self.assertEqual((c["open"], c["todo"], c["todo_done"]), (2, 2, 1))
        self.assertEqual(checklist.window_count(G), ("2건", "보고 전에 볼 것 · 할 일 기록 2건"))
        page = checklist.render(G, "K")
        self.assertLess(page.index("보고 전에 볼 것"), page.index("할 일 기록"))
        self.assertIn("보고를 막지 않", page)

    def test_same_book_notice_is_one_item(self):
        """같은 원인(장부 읽기 알림)이 '입력 자료'와 '변환 알림'에 두 번 나오면 한 건."""
        body = "분개장이 2026-01-01부터라 작년 분개장이 빠졌음 — 수집 폴더에 함께 넣으세요"
        conv = checklist.convert_items([], [], ["[확인] " + body])
        dup = _item("입력|x", kind="입력 자료", choices=("고칠 것", "그대로 둠 (괜찮음)"), same_as=body)
        other = _item("입력|y", kind="입력 자료", same_as="다른 알림")
        out = checklist.drop_same_cause(conv + [dup, other])
        self.assertEqual([it["id"] for it in out], [conv[0]["id"], "입력|y"])

    def test_titles_are_not_cut_and_todo_prefix_dropped(self):
        long = "가" * 150 + " 끝"
        conv = checklist.convert_items([], [], ["[확인] " + long])
        self.assertIn(long, conv[0]["title"] + conv[0]["detail"])
        self.assertTrue(conv[0]["title"].endswith("끝"))
        from ceo_report import mgmt_topics
        out = os.path.join(self.tmp, "출력")
        os.makedirs(os.path.join(out, mgmt_topics.RECORD_DIR))
        with open(os.path.join(out, mgmt_topics.RECORD_DIR, "할일_weekly_2026-10-31.json"), "w", encoding="utf-8") as f:
            json.dump({"items": {"할일|1": {"topic": "cash", "owner": "경영관리", "text": "가상 할 일", "fact": "사실"}}}, f, ensure_ascii=False)
        it = mgmt_topics.check_items(out)[0]
        self.assertEqual(it["title"], "가상 할 일")
        self.assertIn("자금", it["detail"])


class TestItem19ExplicitChoiceState(ChecklistCase):
    def test_todo_choices_wait_for_fix(self):
        """19: 할 일이 남은 선택은 낱말이 아니라 선택지마다 정해 둔 상태로 — 자료에서 풀릴 때까지 보인다."""
        for choice in ("명세서 오면 확정 금액 넣음", "통장 잔액 잘못 넣음", "위하고에 넣을 것", "진행 중 — 확인 필요"):
            self.assertEqual(checklist.choice_state(choice), "fix", choice)
        for choice in ("확인함", "원인 앎 — 그대로 둠", "정상 (별개 거래)", "처리함"):
            self.assertEqual(checklist.choice_state(choice), "done", choice)
        self.assertEqual(checklist.choice_state(""), "open")

    def test_every_choice_in_code_has_a_state(self):
        import glob
        import re
        found = set()
        for p in glob.glob(os.path.join(ROOT, "ceo_report", "*.py")):
            with open(p, encoding="utf-8") as f:
                src = f.read()
            for m in re.finditer(r'"choices":\s*(\(?\[.*?\]\)?)\s*[,})]', src, re.S):
                found.update(re.findall(r'"([^"]+)"', m.group(1)))
        self.assertGreater(len(found), 15)
        missing = sorted(c for c in found if c not in checklist.CHOICE_STATE)
        self.assertEqual(missing, [])


class TestItem20AmountChangeReopens(ChecklistCase):
    def test_decision_is_reopened_when_amount_changes(self):
        """20: '원인 앎 — 그대로 둠'은 그때의 차이 금액과 함께 저장되고, 금액이 달라지면 다시 '결정할 것'으로 보인다."""
        def put(amount):
            checklist.save_convert_items(self.tmp, [_item("자료대조|a|b|c", kind="자료 대조", amount=amount,
                                                          choices=("원인 앎 — 그대로 둠", "고칠 것"))])
        put(100000)
        G = self.gather()
        s = checklist.Session(self.tmp, self.tmp, D(2026, 10, 31))
        s.G = G
        s.decide("자료대조|a|b|c", "원인 앎 — 그대로 둠", "", "내용")
        self.assertEqual(checklist.read_decisions(self.tmp)["자료대조|a|b|c"]["금액"], "100000")
        self.assertEqual(self.mine("자료대조|a|b|c")["state"], "done")
        put(50000000)
        it = self.mine("자료대조|a|b|c")
        self.assertEqual(it["state"], "open")
        self.assertIn("금액 바뀜", it["changed"])
        self.assertIn("100,000", it["changed"])
        self.assertIn("전에 결정함", checklist.render(self.gather(), "K"))

    def test_old_decision_without_amount_is_asked_again(self):
        checklist.save_convert_items(self.tmp, [_item("자료대조|a|b|c", kind="자료 대조", amount=7, choices=("원인 앎 — 그대로 둠", "고칠 것"))])
        checklist.save_decision(self.tmp, "자료대조|a|b|c", "원인 앎 — 그대로 둠")   # 예전 판이 저장한 결정 (금액 없음)
        it = self.mine("자료대조|a|b|c")
        self.assertEqual(it["state"], "open")
        self.assertIn("금액을 적어 두지 않", it["changed"])


class TestItem18SaveRecounts(ChecklistCase):
    def test_saving_returns_new_counts_and_tells_window(self):
        """18: 저장하면 화면 위 건수와 창 건수를 바로 다시 센다. 화면엔 '되돌리기'."""
        told = []
        s = checklist.Session(self.tmp, self.tmp, D(2026, 10, 31), on_saved=told.append, on_counts=told.append)
        s.G = self.G([_item("a"), _item("b")])
        self.assertIn("되돌리기", checklist.render(s.G, "K"))
        s.decide("a", "확인함", "", "")
        self.assertEqual(s.counts()["open"], 1)
        self.assertTrue(any(isinstance(t, dict) and t["open"] == 1 for t in told))


class WinCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.P = app.Paths(self.tmp)
        for d in (self.P.input, self.P.wehago, self.P.output):
            os.makedirs(d)

    def touch(self, path, when, text=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if text is not None else ("{}" if path.endswith(".json") else "x"))
        t = time.mktime(when.timetuple())
        os.utime(path, (t, t))

    def out(self, name, when, text=None):
        self.touch(os.path.join(self.P.output, name), when, text)

    STOP = gate.stop_page("주간 대표보고", ["자금계획서 없음 (수집\\위하고에 자금계획 파일이 없음 — 확장에서 '모두 받기')"])


class TestItem1BlockedIsNotDone(WinCase):
    def test_blocked_week_shows_red_not_done(self):
        """1: 대표 보고가 막힌 주는 3단계가 초록 '완료'가 아니라 빨강 '보고 만들지 않음 — 까닭', 단추는 '까닭 보기'."""
        A = D(2026, 11, 16)
        conv = dt.datetime(2026, 11, 16, 0, 50)
        self.out("2026-11-16_주간_대표보고.html", dt.datetime(2026, 11, 16, 0, 58), self.STOP)
        self.out("2026-11-16_주간_대표보고 (11-15 09시00분 만듦).pdf", dt.datetime(2026, 11, 15, 9, 0))   # 막히기 전 옛 PDF
        self.out("2026-11-16_주간_경영관리보고.html", dt.datetime(2026, 11, 16, 0, 58))
        rows = winstate.reports_for(self.P.output, A)
        ceo = [r for r in rows if r["label"] == "주간 대표"][0]
        self.assertEqual(ceo["state"], "막힘")
        self.assertTrue(ceo["path"].endswith(".html"))             # 옛 PDF 는 넣지 않는다
        self.assertIn("자금계획서 없음", ceo["why"])
        text, kind = winstate.report_chip({"now": 3, "convert": conv}, rows, None)
        self.assertEqual(kind, "bad")
        self.assertEqual(text, "보고 만들지 않음 — 자금계획서 없음")
        self.assertEqual(winstate.open_label(os.path.join(self.P.output, "2026-11-16_주간_대표보고.html")), "까닭 보기")

    def test_done_only_when_this_asof_pdf_exists(self):
        A = D(2026, 11, 16)
        conv = dt.datetime(2026, 11, 16, 9, 0)
        self.out("2026-11-09_주간_대표보고.html", dt.datetime(2026, 11, 16, 9, 30))        # 다른 기준일 보고
        self.out("2026-11-09_주간_대표보고 (11-16 09시30분 만듦).pdf", dt.datetime(2026, 11, 16, 9, 30))
        rows = winstate.reports_for(self.P.output, A)
        self.assertEqual(winstate.report_chip({"now": 3, "convert": conv}, rows, None), ("지금 할 차례", "now"))
        self.out("2026-11-16_주간_대표보고.html", dt.datetime(2026, 11, 16, 9, 40))
        self.out("2026-11-16_주간_대표보고 (11-16 09시40분 만듦).pdf", dt.datetime(2026, 11, 16, 9, 40))
        rows = winstate.reports_for(self.P.output, A)
        self.assertEqual(winstate.report_chip({"now": 3, "convert": conv}, rows, None), ("완료 11/16 09:40", "ok"))
        self.assertEqual(winstate.report_chip({"now": 2, "convert": conv}, rows, None), ("변환 뒤", "wait"))

    def test_known_block_before_pressing(self):
        """2: 누르기 전에도 막힐지 보인다 (보고와 같은 판단)."""
        G = {"problems": ["자금계획서 없음 (수집 폴더에 없음)"], "book_date": D(2026, 11, 14), "plan_date": None}
        self.assertEqual(winstate.report_chip({"now": 3, "convert": dt.datetime(2026, 11, 16)}, [], G), ("막힘 — 자금계획서 없음", "bad"))
        text, ok = winstate.gate_line(G)
        self.assertFalse(ok)
        self.assertTrue(text.startswith("대표 보고: 막힘 — 자금계획서 없음 → "))
        self.assertIn("모두 받기", text)
        self.assertEqual(winstate.gate_line({"problems": [], "book_date": D(2026, 11, 14), "plan_date": D(2026, 11, 15)}),
                         ("대표 보고: 만들 수 있음 (분개장 11/14 · 자금계획서 11/15)", True))
        self.assertEqual(winstate.gate_line(None), ("대표 보고: 확인 중…", None))


class TestItem2FreshnessShowsBookDate(WinCase):
    def test_book_date_and_red_when_blocked(self):
        A = D(2026, 11, 16)
        self.touch(os.path.join(self.P.wehago, "261116 분개장 자동수집.json"), dt.datetime(2026, 11, 16, 9, 0))
        G = {"problems": ["분개장 자료일 2026-11-01 — 기준일보다 15일 전 (허용 7일)", "자금계획서 없음 (…)"],
             "book_date": D(2026, 11, 1), "plan_date": None}
        F = {f["name"]: f for f in winstate.freshness(self.P, A, G)}
        self.assertEqual(F["분개장"]["level"], "r")                     # 받은 시각은 오늘이어도 장부 자료일이 오래됨
        self.assertIn("자료일 11/1", F["분개장"]["text"])
        self.assertEqual(F["자금계획서"]["level"], "r")                 # '없음'이 회색이 아니라 빨강 (보고가 막힘)
        F = {f["name"]: f for f in winstate.freshness(self.P, A)}        # 판단을 아직 모르면 예전처럼
        self.assertEqual((F["분개장"]["level"], F["자금계획서"]["level"]), ("g", "none"))

    def test_gate_status_matches_report_gate(self):
        """창의 판단은 보고가 쓰는 gate.problems 와 같은 것."""
        inp = os.path.join(self.tmp, "샘플입력")
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), inp)
        env = dict(os.environ)
        env.pop("CEO_REPORT_TEST_GATE_OFF", None)
        with mock.patch.dict(os.environ, env, clear=True):
            G = gate.status_dir(inp, D(2026, 10, 31))
            self.assertEqual(G["problems"], gate.check_dir(inp, D(2026, 10, 31)))
        self.assertTrue(any("자금계획서" in p for p in G["problems"]))   # 샘플엔 자금계획서가 없음
        self.assertEqual(gate.short(G["problems"][0]), "자금계획서 없음")


class TestRuleOps03FridayPayday(unittest.TestCase):
    """운영-03 (결정 카드 ② '지금처럼 + 출금일 표시', 편의성 3): 기본 출금일은 그대로(기준일 뒤 첫 금요일),
    주간 보고 단추 옆에 실제 출금일·이체 기간을 보이고 금요일엔 '오늘 출금용' 단추."""

    def test_default_unchanged_and_line_shows_real_values(self):
        fri = D(2026, 11, 20)
        self.assertEqual(winstate.next_friday(fri), D(2026, 11, 27))                    # 기본값은 바꾸지 않음
        self.assertEqual(winstate.pay_line(fri, ""), "출금 11/27(금) · 이체 11/21~11/27")
        self.assertEqual(winstate.pay_line(fri, "2026-11-25"), "출금 11/25(수) · 이체 11/21~11/25")
        self.assertEqual(winstate.pay_line(None, ""), "")

    def test_today_button_only_on_friday_default(self):
        fri, thu = D(2026, 11, 20), D(2026, 11, 19)
        self.assertEqual(winstate.today_pay_asof(fri, "2026-11-20", ""), thu)            # 기준일을 어제로 → 출금일이 오늘
        self.assertEqual(winstate.next_friday(thu), fri)
        self.assertIsNone(winstate.today_pay_asof(thu, "2026-11-19", ""))                # 금요일이 아니면 없음
        self.assertIsNone(winstate.today_pay_asof(fri, "2026-11-19", ""))                # 이미 어제 기준
        self.assertIsNone(winstate.today_pay_asof(fri, "2026-11-20", "2026-11-27"))      # 출금일을 직접 넣었으면 없음


class TestItem4AsofFollowsToday(unittest.TestCase):
    def test_untouched_asof_rolls_and_edited_stays(self):
        old, new = D(2026, 11, 16), D(2026, 11, 17)
        self.assertEqual(winstate.roll_asof("2026-11-16", old, new)[0], "2026-11-17")
        self.assertIn("기준일을 오늘", winstate.roll_asof("2026-11-16", old, new)[1])
        self.assertEqual(winstate.roll_asof("2026-11-10", old, new), ("2026-11-10", ""))   # 직접 고친 날짜는 그대로
        self.assertEqual(winstate.roll_asof("2026-11-16", old, old), ("2026-11-16", ""))
        self.assertEqual(winstate.asof_note("2026-11-10", new), "오늘과 다름")
        self.assertEqual(winstate.asof_note("2026-11-17", new), "")


class TestItem6OnePrimaryAction(unittest.TestCase):
    def test_only_current_step_is_blue(self):
        ok = {"problems": []}
        self.assertEqual(winstate.primary_action({"now": 1}, None), "collect")
        self.assertEqual(winstate.primary_action({"now": 2}, ok), "convert")
        self.assertEqual(winstate.primary_action({"now": 3}, ok), "report")
        self.assertIsNone(winstate.primary_action({"now": 3}, {"problems": ["자금계획서 없음"]}))   # 막히면 보고 단추도 파랗지 않음


class TestItem8StatusLine(unittest.TestCase):
    def test_cause_specific_errors(self):
        ok, t = winstate.rc_message("인트라넷", 5)
        self.assertFalse(ok)
        self.assertIn("연결", t)
        self.assertIn("다시", t)
        self.assertNotIn("코드 5", t)
        ok, t = winstate.rc_message("주간", 7, locked=True)
        self.assertIn("변환이 아직 끝나지", t)
        self.assertIn("15분", t)
        self.assertNotIn("PDF가 열려", t)

    def test_important_lines(self):
        self.assertTrue(winstate.important("[확인] 분개장이 2026-01-01부터라 작년 분개장이 빠졌음"))
        self.assertTrue(winstate.important("자금계획서 없음 → 가용자금은 자금일정으로"))
        self.assertFalse(winstate.important("거래내역.csv 1,234줄 만듦"))
        self.assertFalse(winstate.important("  F:\\CLAUDE\\CEO_REPORT\\입력\\거래처.csv"))


class TestItem29PdfStates(WinCase):
    def test_weekly_and_monthly_are_reported_apart(self):
        """29: 자동 반영에서 월간 PDF만 못 만들어도 '다시 만들었습니다'가 아니라 따로 보인다."""
        files = [os.path.join(self.P.output, n) for n in (
            "2026-11-16_주간_대표보고.html", "2026-11-16_주간_대표보고 (11-16 09시00분 만듦).pdf",
            "2026-11-16_월간_대표보고.html", "2026-11-16_월간_경영관리보고.html")]
        for f in files:
            self.touch(f, dt.datetime(2026, 11, 16, 9, 0))
        st = winstate.pdf_states(files)
        self.assertEqual(st, {"주간": "PDF 만듦", "월간": "PDF 못 만듦"})
        ok, line = winstate.outcome("자동", 0, files)
        self.assertFalse(ok)
        self.assertIn("주간 PDF 만듦", line)
        self.assertIn("월간 PDF 못 만듦", line)
        self.assertEqual(winstate.failed_kinds(files), ["월간"])


class TestItem9MergeModes(WinCase):
    def test_three_modes_and_zero_picked_is_not_all(self):
        """9: '건별 / 모두 합침 / 고른 곳만 합침'을 따로. 고른 곳이 0곳이면 '모두'로 읽지 않는다."""
        self.assertEqual(app.merge_args("건별", "가, 나"), ("건별", ""))
        self.assertEqual(app.merge_args("거래처별", "가, 나"), ("거래처별", ""))        # 모두 합침: 고른 목록은 쓰지 않음
        self.assertEqual(app.merge_args("고른곳만", "가, 나"), ("거래처별", "가, 나"))
        self.assertEqual(app.merge_args("고른곳만", ""), ("건별", ""))                  # 0곳 = 합치지 않음
        app.save_merge(self.P, "고른곳만", "가, 나")
        self.assertEqual(app.load_merge(self.P), ("고른곳만", "가, 나"))
        app.save_merge(self.P, "거래처별", "가")
        self.assertEqual(app.load_merge(self.P), ("거래처별", "가"))                    # 모두 합침이어도 고른 목록은 남겨 둠

    def test_old_saved_file_keeps_its_meaning(self):
        with open(os.path.join(self.P.input, app.MERGE_FILE), "w", encoding="utf-8") as f:
            f.write("거래처별\n가, 나\n")       # 예전 판: 거래처별 + 고른 곳 = 그 곳만 합침
        self.assertEqual(app.load_merge(self.P), ("고른곳만", "가, 나"))
        with open(os.path.join(self.P.input, app.MERGE_FILE), "w", encoding="utf-8") as f:
            f.write("거래처별\n\n")              # 예전 판: 고른 곳 없음 = 모두 합침
        self.assertEqual(app.load_merge(self.P), ("거래처별", ""))

    def test_report_gets_the_translated_args(self):
        name, argv = app.task_argv("주간", self.P, "2026-11-16", group="고른곳만", only="가, 나")
        self.assertEqual(argv[argv.index("--출금목록") + 1], "거래처별")
        self.assertEqual(argv[argv.index("--합칠거래처") + 1], "가, 나")
        name, argv = app.task_argv("주간", self.P, "2026-11-16", group="고른곳만", only="")
        self.assertEqual(argv[argv.index("--출금목록") + 1], "건별")
        self.assertNotIn("--합칠거래처", argv)


class TestItem22ScheduleEdit(WinCase):
    def add(self, **kw):
        base = dict(day="2026-11-30", io_kind="지급", amount="3,300,000", firm="예상", vendor="가상업체", memo="가상")
        base.update(kw)
        return app.add_schedule(self.P.input, **base)

    def test_list_edit_delete_in_window(self):
        """22: 지급·입금 예정은 CSV 를 열지 않고 창 안 목록에서 고치고 지운다."""
        self.add()
        self.add(vendor="둘째업체", amount="1,000")
        rows = occasional.schedule_rows(self.P.input)
        self.assertEqual([r["거래처"] for r in rows], ["가상업체", "둘째업체"])
        occasional.update_schedule(self.P.input, rows[0], {"금액": "4,400,000", "확정여부": "확정", "예정일": "2026-12-01"})
        rows = occasional.schedule_rows(self.P.input)
        self.assertEqual((rows[0]["금액"], rows[0]["확정여부"], rows[0]["예정일"], rows[0]["비고"]), ("4,400,000", "확정", "2026-12-01", "가상"))
        occasional.delete_schedule(self.P.input, rows[1])
        self.assertEqual([r["거래처"] for r in occasional.schedule_rows(self.P.input)], ["가상업체"])

    def test_changed_file_is_not_overwritten(self):
        self.add()
        rows = occasional.schedule_rows(self.P.input)
        self.add(vendor="새로 들어온 줄")
        stale = dict(rows[0], 금액="1")           # 화면에 보인 줄과 파일의 줄이 다름
        with self.assertRaises(ValueError):
            occasional.delete_schedule(self.P.input, stale)
        with self.assertRaises(ValueError):
            occasional.update_schedule(self.P.input, rows[0], {"금액": "숫자아님"})
        self.assertEqual(len(occasional.schedule_rows(self.P.input)), 2)

    def test_cp949_file_keeps_encoding(self):
        with open(os.path.join(self.P.input, app.SCHED_FILE), "w", encoding="cp949", newline="") as f:
            f.write("예정일,입출금,금액,확정여부,분류,프로젝트번호,거래처,근거,비고\r\n2026-11-30,지급,1000,예상,기타지급,,가상업체,직접 입력,\r\n")
        rows = occasional.schedule_rows(self.P.input)
        occasional.update_schedule(self.P.input, rows[0], {"금액": "2,000"})
        with open(os.path.join(self.P.input, app.SCHED_FILE), encoding="cp949") as f:
            self.assertIn("가상업체", f.read())

    def test_blank_keeps_and_delete_buttons(self):
        """22: 빈칸은 어디서나 '그대로', 지울 땐 '지우기'."""
        from ceo_report import targets, corptax
        app.save_team_target(self.P.input, "2026", "기획1팀", "1,000,000", "30")
        self.assertEqual(occasional.saved_target(self.P.input, "2026", "기획1팀"), ("1,000,000", "30"))
        self.assertEqual(occasional.saved_target(self.P.input, "2026", "기획2팀"), ("", ""))
        occasional.delete_target(self.P.input, "2026", "기획1팀")
        self.assertEqual(targets.read(self.P.input), {})
        app.save_depreciation(self.P.input, "2026", "12,000,000")
        self.assertEqual(occasional.saved_dep(self.P.input, "2026"), "12,000,000")
        app.save_card(self.P.input, "신한", "15", "1")
        app.save_card(self.P.input, "롯데", "25", "5")
        self.assertEqual(occasional.saved_card(self.P.input, "롯데"), ("25", "5"))
        occasional.delete_card(self.P.input, "롯데")
        self.assertEqual(occasional.saved_card(self.P.input, "롯데"), ("", ""))
        self.assertEqual(occasional.saved_card(self.P.input, "신한"), ("15", "1"))
        app.save_budget_values(self.P.input, "2027", [("성장률", "기획1팀", "10"), ("급여인상률", "", "5")])
        self.assertEqual(occasional.saved_budget(self.P.input, "2027", "기획1팀"),
                         {"성장률": "10", "늘릴인원": "", "입사월": "", "급여인상률": "5", "물가인상률": ""})


class TestItem23LoanMaturity(WinCase):
    def test_rows_and_save(self):
        """23: 대출 새 만기일을 창에서 넣는다 (대출만기.csv). 신용평가의 '가장 이른 만기'와는 다른 값이라 합치지 않는다."""
        from ceo_report import reconcile
        rows = occasional.maturity_rows(self.P.input)            # 파일이 없으면 알려 주신 기본 두 줄
        self.assertEqual([r["거래처코드"] for r in rows], ["256", "1107"])
        occasional.save_maturity(self.P.input, "1107", "신한 기술보증기금 3억", "2028-04-21", True, "2027-04 연장 확인")
        M = reconcile.read_maturity(self.P.input)
        self.assertEqual((M["1107"]["새만기일"], M["1107"]["매년연장"], M["1107"]["메모"]), ("2028-04-21", "예", "2027-04 연장 확인"))
        self.assertEqual(M["256"]["새만기일"], "2027-04-17")     # 다른 대출 줄은 그대로
        with self.assertRaises(ValueError):
            occasional.save_maturity(self.P.input, "1107", "x", "2028-13-01", True, "")
        with self.assertRaises(ValueError):
            occasional.save_maturity(self.P.input, "1107", "x", "2028-04-21", True, "")   # 근거 메모 없이 새 만기일만
        self.assertNotIn("대출만기일", [k for k in M["1107"]])    # 신용평가 값과 섞지 않음


class TestItem24HolderLoad(WinCase):
    def test_saved_holder_comes_back_with_checks(self):
        """24: 저장된 주주를 불러오면 '미성년자·회사 급여' 체크까지 채워진다 (다시 저장할 때 풀리지 않게)."""
        app.save_holder(self.P.input, "가상주주", "40", True, True, "1,000,000", "", False, "2")
        h = occasional.saved_holder(self.P.input, "가상주주")
        self.assertEqual((h["지분율"], h["미성년자"], h["회사급여"], h["다른금융소득"], h["공제인원"]), ("40", True, True, "1,000,000", "2"))
        self.assertEqual(occasional.holder_names(self.P.input), ["가상주주"])
        self.assertIsNone(occasional.saved_holder(self.P.input, "없는사람"))


class TestItem26ForgetWhenUnchecked(WinCase):
    def test_remember_state(self):
        from ceo_report import credstore
        self.assertEqual(occasional.remember_text(self.P.input), "기억한 계정 없음")
        credstore.save(self.P.input, "가상아이디", "가상비밀")
        self.assertEqual(occasional.remember_text(self.P.input), "기억 중: 가상아이디")


if __name__ == "__main__":
    unittest.main()
