import datetime as dt
import tempfile
import unittest

from ceo_report import taxlaw as tl


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


if __name__ == "__main__":
    unittest.main()
