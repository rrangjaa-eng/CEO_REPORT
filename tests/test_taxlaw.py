import datetime as dt
import tempfile
import unittest

from unittest import mock

from ceo_report import taxlaw as tl

# 2026-11-17: 실제 2026 기준표엔 이제 미확인 값이 없음(통합고용 금액을 법령으로 확인) → 미확인·시행일 처리 시험은 가짜 미확인 값으로
UNVERIFIED = mock.patch.dict(tl.DEFAULTS[2026], {
    "고용공제_수도권": (None, "미확인", "시험용 미확인", dt.date(2026, 7, 1)),
    "고용공제_지방": (None, "미확인", "시험용 미확인", dt.date(2026, 7, 1))})


@UNVERIFIED
class Law(unittest.TestCase):
    def test_defaults_and_unverified(self):
        d = tempfile.mkdtemp()
        self.assertEqual(tl.value(d, 2026, "최저한세율")[:2], (0.07, True))       # 2025 값 이어 씀 (자료확인)
        v, ok, why = tl.value(d, 2026, "고용공제_수도권")
        self.assertFalse(ok)
        self.assertIn("미확인", why)

    def test_new_year_without_defaults_is_unverified(self):
        v, ok, why = tl.value(tempfile.mkdtemp(), tl.LATEST + 1, "최저한세율")
        self.assertEqual(v, 0.07)
        self.assertFalse(ok)
        self.assertIn("개정 확인 필요", why)

    def test_confirm_and_recheck_after_effective_date(self):
        d = tempfile.mkdtemp()
        tl.confirm(d, 2026, {"고용공제_수도권": "9,000,000"}, "세무사", today=dt.date(2026, 3, 1))
        self.assertFalse(tl.value(d, 2026, "고용공제_수도권", today=dt.date(2026, 8, 1))[1])   # 7/1 시행 개정 뒤 다시 확인
        self.assertTrue(tl.value(d, 2026, "고용공제_수도권", today=dt.date(2026, 5, 1))[1])
        tl.confirm(d, 2026, {"최저한세율": "7%", "고용공제_수도권": None}, today=dt.date(2026, 8, 2))
        self.assertEqual(tl.value(d, 2026, "최저한세율"), (0.07, True, "확인함 2026-08-02"))
        self.assertTrue(tl.value(d, 2026, "고용공제_수도권", today=dt.date(2026, 9, 1))[1])

    def test_confirm_without_value_refused(self):
        with self.assertRaises(ValueError):
            tl.confirm(tempfile.mkdtemp(), 2026, {"고용공제_지방": None})

    def test_banner_and_render(self):
        from ceo_report.util import esc
        T = tl.status(tempfile.mkdtemp(), 2026)
        self.assertIn("미확인", tl.banner(T))
        self.assertIn("적용한 세법 기준", tl.render(T, esc))


@UNVERIFIED
class AppLines(unittest.TestCase):
    def test_law_text_and_percent_without_sign(self):
        import tempfile
        from ceo_report import app, taxlaw
        d = tempfile.mkdtemp()
        self.assertIn("미확인", app.law_text(d, 2026))
        taxlaw.confirm(d, 2026, {"국민연금요율": "9.5"}, "세무사")
        self.assertEqual(taxlaw.value(d, 2026, "국민연금요율")[0], 0.095)
        with self.assertRaises(ValueError):
            app.law_check(d, 2026)   # OC 아이디 없음


class Hire2026Defaults(unittest.TestCase):
    def test_hire_amounts_from_law_1117(self):
        # 조특법 29조의8 (2025-12-23 개정) 중소기업 직전 해 대비 1명당: 수도권 400만·청년 등 700만, 밖 700만·1,000만
        d = tempfile.mkdtemp()
        self.assertEqual([tl.value(d, 2026, k)[:2] for k in ("고용공제_수도권", "고용공제_수도권청년", "고용공제_지방", "고용공제_지방청년")],
                         [(4_000_000, True), (7_000_000, True), (7_000_000, True), (10_000_000, True)])


if __name__ == "__main__":
    unittest.main()
