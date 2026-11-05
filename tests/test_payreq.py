"""지급 요청서 세부사항 첫 줄 → 주간 출금 목록 상세 내역 (사용자 2026-11-05). 모든 글자는 가상 자료."""
import datetime as dt
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import intranet, payreq  # noqa: E402

D = dt.date

# 실제 화면 구조(값을 가린 사본, 2026-11-05)를 본뜬 가상 지급 요청서
PREVIEW = """<html><body>
<div style="float:right"><a href="/preview/paymentwrite?pro_num=12&amp;quo_num=345&amp;cmd=print"><img></a></div>
<table><form name="frm1" method="post" action="/preview/poppaymentsubmit"></form>
<input type="hidden" name="pro_num" value="12"><input type="hidden" name="quo_company" value="가상상사">
<tbody><tr><td><table><tbody><tr bgcolor="#FFFFFF"><td width="150">업체명 </td><td colspan="3">가상상사 (주)</td></tr>
<tr><td width="150">금액(부가세포함) </td><td><input name="pay_money" type="text" value="1,650,000" onkeyup="cmaComma(this);">원</td>
<td>구분</td><td><select name="tax"><option value="부가세" selected>부가세</option></select></td></tr>
<tr><td>지급희망 일자</td><td><input name="pay_date" value="2026.11.13"></td></tr>
<tr><td>은행 계좌</td><td><input name="pay_account" value="가상은행 000-000"></td></tr>
<tr><td colspan="4"><table><tbody><tr><td width="19%">프로젝트 명 : </td><td>[26101] 가상 전시 부스</td></tr>
<tr><td>행사명 : </td><td>가상 행사</td></tr></tbody></table>
<table><tbody><tr><td>품목</td><td>단가</td></tr><tr><td>목공</td><td>1,500,000</td></tr></tbody></table></td></tr>
<tr><td colspan="4"><table><tbody><tr><td width="15%">세부사항 : </td>
<td><textarea name="pay_remark" rows="17">

  부스 목공 제작 잔금 &amp; 설치
둘째 줄은 넣지 않음</textarea></td></tr></tbody></table></td></tr>
</tbody></table></td></tr></tbody></table></body></html>"""

ROW = ("<table><tr><td>7</td><td><a href=\"/project/payment?pro_num=12\">[26101] 가상 전시 부스</a></td>"
       "<td><a href=\"javascript:payment_pop('/preview/paymentwrite?pro_num=12&amp;quo_num=345,346&amp;cmd=check')\">가상상사</a></td>"
       "<td>2026-11-01 10:00:00</td><td>2026.11.20</td><td>1,650,000</td><td>2026.11.13</td><td>가상직원</td>"
       "<td>수락완료</td><td><a href=\"javascript:checkconfirm('반려하시겠습니까?','/confirm/cancel?mode=admin&amp;num=1')\">반려</a></td>"
       "<td>미승인</td><td><a href=\"javascript:checkconfirm('삭제하시겠습니까?','/confirm/del?num=1')\">삭제</a></td></tr></table>")


class TestParse(unittest.TestCase):
    def test_preview_values_and_first_line_only(self):
        r = payreq.parse_preview(PREVIEW)
        self.assertEqual(r, {"project": "26101", "vendor": "가상상사 (주)", "amount": 1650000,
                             "note": "부스 목공 제작 잔금 & 설치"})

    def test_list_row_link_and_admin_state(self):
        row = intranet.parse_tables(ROW)[0].rows[0]
        p = intranet._map_payment(row)
        self.assertEqual(p["_preview"], "pro_num=12&quo_num=345,346&cmd=check")
        self.assertTrue(payreq.wanted(p))
        # 관리팀 칸 '승인' = 아직 승인 버튼(관리팀 안 함) · '수락완료' = 사장님까지 끝 → 안 읽음
        for admin, ceo in (("승인", "미승인"), ("수락완료", "수락완료"), ("반려", "수락완료")):
            self.assertFalse(payreq.wanted(dict(p, 관리팀승인=admin, 사장님승인=ceo)), (admin, ceo))

    def test_only_preview_check_is_allowed(self):
        ok = intranet.check_url("GET", intranet.BASE + "/preview/paymentwrite?pro_num=12&quo_num=345,346&cmd=check")
        self.assertTrue(ok.endswith("cmd=check"))
        for bad in ("/preview/paymentwrite?pro_num=12&quo_num=345&cmd=print",
                    "/preview/paymentwrite?pro_num=12&quo_num=345&cmd=check&x=1",
                    "/preview/poppaymentsubmit?pro_num=12",
                    "/confirm/cancel?mode=admin&num=1"):
            with self.assertRaises(intranet.BlockedRequest):
                intranet.check_url("GET", intranet.BASE + bad)
        with self.assertRaises(intranet.BlockedRequest):
            intranet.check_url("POST", intranet.BASE + "/preview/paymentwrite?pro_num=12&quo_num=345&cmd=check")


class FakeOpener(object):
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        return 200, url, self.pages.get(url, "")


class TestCollect(unittest.TestCase):
    def test_reads_only_wanted_rows(self):
        url = intranet.BASE + "/preview/paymentwrite?pro_num=12&quo_num=345&cmd=check"
        op = FakeOpener({url: PREVIEW})
        pays = [{"관리팀승인": "반려", "사장님승인": "미승인", "_preview": "pro_num=12&quo_num=345&cmd=check"},
                {"관리팀승인": "승인", "사장님승인": "미승인", "_preview": "pro_num=13&quo_num=1&cmd=check"},
                {"관리팀승인": "수락완료", "사장님승인": "수락완료", "_preview": "pro_num=14&quo_num=1&cmd=check"}]
        out = intranet.collect_requests(op, pays)
        self.assertEqual(op.urls, [url])
        self.assertEqual([(r["key"], r["note"]) for r in out], [("pro_num=12&quo_num=345&cmd=check", "부스 목공 제작 잔금 & 설치")])

    def test_unknown_page_stops_details_only(self):
        url = intranet.BASE + "/preview/paymentwrite?pro_num=12&quo_num=345&cmd=check"
        pays = [{"관리팀승인": "반려", "사장님승인": "미승인", "_preview": "pro_num=12&quo_num=345&cmd=check"}]
        self.assertIsNone(intranet.collect_requests(FakeOpener({url: "<html>다른 화면</html>"}), pays))

    def test_file_round_trip(self):
        rows = [{"key": "pro_num=1&quo_num=2&cmd=check", "project": "26101", "vendor": "가상", "amount": 1000, "note": "메모"}]
        with tempfile.TemporaryDirectory() as tmp:
            payreq.write(tmp, rows)
            self.assertEqual(payreq.read(tmp), rows)


def ev(amount, project="26101", desc="가상상사", detail=None, src=None):
    e = {"io": "out", "date": D(2026, 11, 6), "amount": amount, "project": project, "desc": desc}
    if detail:
        e["detail"], e["detail_source"] = detail, src
    return e


def rq(amount, note, project="26101", vendor="가상상사(주)"):
    return {"key": note, "project": project, "vendor": vendor, "amount": amount, "note": note}


class TestAttach(unittest.TestCase):
    def test_project_and_amount_even_if_vendor_name_differs(self):
        e = ev(1650000, desc="주식회사 전혀다른이름")
        self.assertEqual(payreq.attach([e], [rq(1650000, "목공 잔금")]), 1)
        self.assertEqual((e["detail"], e["detail_source"]), ("목공 잔금", "지출결의서"))

    def test_other_project_or_amount_not_attached(self):
        a, b = ev(1650000, project="26102"), ev(1650001)
        self.assertEqual(payreq.attach([a, b], [rq(1650000, "목공 잔금")]), 0)
        self.assertNotIn("detail", a)
        self.assertNotIn("detail", b)

    def test_same_amount_twice_uses_vendor_else_nothing(self):
        e = ev(500, desc="(주)나라")
        reqs = [rq(500, "가 건", vendor="가람"), rq(500, "나 건", vendor="나라 주식회사")]
        payreq.attach([e], reqs)
        self.assertEqual(e["detail"], "나 건")
        e2 = ev(500, desc="다른곳")
        payreq.attach([e2], [rq(500, "가 건", vendor="가람"), rq(500, "나 건", vendor="나라")])
        self.assertNotIn("detail", e2)

    def test_sum_of_requests_matches_one_payment(self):
        e = ev(800)
        payreq.attach([e], [rq(300, "운송"), rq(500, "설치")])
        self.assertEqual(e["detail"], "운송 · 설치")

    def test_undated_rows_and_prefixed_project_ids(self):
        """날짜 없는 일정 줄이 있어도 멈추지 않고, 'P26101' 같은 번호도 5자리로 맞춤."""
        a, b = ev(1000, project="P26101"), dict(ev(2000), date=None)
        self.assertEqual(payreq.attach([a, b], [rq(1000, "가"), rq(2000, "나")]), 2)
        self.assertEqual((a["detail"], b["detail"]), ("가", "나"))

    def test_manual_detail_wins_and_empty_note_skipped(self):
        e = ev(1000, detail="손으로 넣음", src="수기")
        e2 = ev(2000)
        payreq.attach([e, e2], [rq(1000, "인트라넷"), rq(2000, "")])
        self.assertEqual(e["detail"], "손으로 넣음")
        self.assertNotIn("detail", e2)


if __name__ == "__main__":
    unittest.main()
