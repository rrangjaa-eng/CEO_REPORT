"""WEHAGO 장부 읽기와 인트라넷 대조 시험.

모든 엑셀은 시험 때 임시 폴더에 가상 자료로 만든다. 실제 WEHAGO 파일과 바이너리는 저장소에 없다.
머리글만 실제 파일과 같고, 이름·금액은 모두 가상이다.
"""
import copy
import datetime as dt
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
from test_approval import FAKE_PAYMENTS, write_fake_snapshot  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력")
ASOF = dt.date(2026, 11, 2)
NOW = dt.datetime(2026, 11, 2, 0, 0)


def mod(name):
    return importlib.import_module("ceo_report." + name)


def setUpModule():
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py")], check=True,
                   stdout=subprocess.DEVNULL)


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


# ───────────── 가상 xlsx 쓰기 (zipfile 만 쓴다) ─────────────
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _t(text):
    return '<t xml:space="preserve">%s</t>' % escape(text)


def _sheet_xml(rows, strings, inline):
    out = ['<worksheet xmlns="%s"><sheetData>' % _MAIN]
    for n, row in enumerate(rows, 1):
        out.append('<row r="%d">' % n)
        for i, v in enumerate(row):
            ref = "%s%d" % (_col(i), n)
            if v is None:
                continue
            if isinstance(v, tuple):  # 특수 칸: ('e', '#REF!') ('str', '글') ('n', '4.4E7') ('rich', ['가', '상']) ('inline', '글')
                kind, val = v
                if kind == "e":
                    out.append('<c r="%s" t="e"><v>%s</v></c>' % (ref, escape(val)))
                elif kind == "b":
                    out.append('<c r="%s" t="b"><v>%s</v></c>' % (ref, escape(val)))
                elif kind == "str":
                    out.append('<c r="%s" t="str"><v>%s</v></c>' % (ref, escape(val)))
                elif kind == "n":
                    out.append('<c r="%s"><v>%s</v></c>' % (ref, escape(val)))
                elif kind == "inline":
                    out.append('<c r="%s" t="inlineStr"><is>%s</is></c>' % (ref, _t(val)))
                elif kind == "rich":
                    strings.append(list(val))
                    out.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, len(strings) - 1))
                continue
            if isinstance(v, (int, float)):
                out.append('<c r="%s"><v>%s</v></c>' % (ref, v if isinstance(v, int) else repr(v)))
            elif inline:
                out.append('<c r="%s" t="inlineStr"><is>%s</is></c>' % (ref, _t(v)))
            else:
                strings.append(v)
                out.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, len(strings) - 1))
        out.append("</row>")
    out.append("</sheetData></worksheet>")
    return _XML + "".join(out)


def _shared_xml(strings):
    out = ['<sst xmlns="%s" count="%d" uniqueCount="%d">' % (_MAIN, len(strings), len(strings))]
    for s in strings:
        if isinstance(s, list):
            out.append("<si>%s</si>" % "".join("<r>%s</r>" % _t(run) for run in s))
        else:
            out.append("<si>%s</si>" % _t(s))
    out.append("</sst>")
    return _XML + "".join(out)


def write_xlsx(path, rows, first_part="sheet1.xml", extra_sheet=None, inline=False, date1904=False,
               raw_sheet_xml=None):
    """가상 엑셀 한 개를 쓴다. 첫 시트는 workbook.xml 순서와 rels 로 찾아야 하도록 부품 이름·관계 번호를 어긋나게 둔다."""
    strings = []
    first = raw_sheet_xml if raw_sheet_xml is not None else _sheet_xml(rows, strings, inline)
    extra_part = "sheet1.xml" if first_part != "sheet1.xml" else "sheet2.xml"
    extra = _sheet_xml(extra_sheet, strings, inline) if extra_sheet is not None else None
    sheets = '<sheet name="자료" sheetId="1" r:id="rId2"/>'
    rels = ['<Relationship Id="rId2" Type="%s/worksheet" Target="worksheets/%s"/>' % (_REL, first_part),
            '<Relationship Id="rId9" Type="%s/sharedStrings" Target="sharedStrings.xml"/>' % _REL]
    if extra is not None:
        sheets += '<sheet name="다른 시트" sheetId="2" r:id="rId1"/>'
        rels.append('<Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/%s"/>' % (_REL, extra_part))
    workbook = (_XML + '<workbook xmlns="%s" xmlns:r="%s"><workbookPr%s/><sheets>%s</sheets></workbook>'
                % (_MAIN, _REL, ' date1904="1"' if date1904 else "", sheets))
    types = (_XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/></Types>')
    root_rels = (_XML + '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/officeDocument" '
                 'Target="xl/workbook.xml"/></Relationships>' % (_PKG_REL, _REL))
    wb_rels = _XML + '<Relationships xmlns="%s">%s</Relationships>' % (_PKG_REL, "".join(rels))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/" + first_part, first)
        if extra is not None:
            z.writestr("xl/worksheets/" + extra_part, extra)
        z.writestr("xl/sharedStrings.xml", _shared_xml(strings))
    return path


# ───────────── 가상 장부 (실제 파일과 같은 머리글, 이름·금액은 가상) ─────────────
JOURNAL_HEADER = ["전표일자", "전표번호", "구분", "Code", "계정과목", "차변", "대변", "거래처", "Code", "적요"]
LEDGER_HEADER = ["구분", "전표일자", "번호", "거래처", "사업자(주민)번호", "품명", "공급가액", "부가세", "합계", "신고월",
                 "전자세금", "11일\n이내", "매입/매출\n유형", "분개유형"]
EINVOICE_HEADER = ["일자", "Code", "거래처", "유형", "품명", "공급가액", "부가세", "합계", "차변계정", "대변계정", "관리",
                   "전표상태"]
KIND_FILES = (("분개장", JOURNAL_HEADER), ("매입매출장", LEDGER_HEADER), ("전자세금계산서(매입)", EINVOICE_HEADER))


def serial(d):
    return (d - dt.date(1899, 12, 30)).days


def _L(kind, date, no, vendor, biz, item, supply, vat):
    return [kind, date, no, vendor, biz, item, supply, vat, supply + vat, "2026-10", "전자", "예", "과세", "외상"]


FAKE_LEDGER = [
    _L("매입", "2026-10-20", 1, "(주)가상음향", "000-00-00001", "[26201] 가상 컨퍼런스 음향", 40000000, 4000000),
    _L("매입", "2026-10-21", 2, "㈜가상제작", "000-00-00002", "[26220] 가상 전시 제작", 150000000, 15000000),
    _L("매입", "2026-10-22", 3, "주식회사 가상부스", "000-00-00003", "[26203] 가상 전시부스", 45000000, 4500000),
    _L("매입", "2026-10-15", 4, "가상 조명", "000-00-00004", "[26220] 가상 전시 조명", 1000000, 100000),
    _L("매입", "2026-10-23", 5, "가상인력", "000-00-00005", "[26220] 가상 전시 인력", 5000000, 500000),
    _L("매입", "2026-10-24", 6, "가상인력", "000-00-00005", "[26220] 가상 전시 인력 추가", 2000000, 200000),
    _L("매입", "2026-10-25", 7, "(주) 가상버스", "000-00-00006", "[26221] 가상 워크숍 버스 1차", 2700000, 270000),
    _L("매입", "2026-10-26", 8, "(주) 가상버스", "000-00-00006", "[26221] 가상 워크숍 버스 2차", 2700000, 270000),
    _L("매출", "2026-10-27", 9, "가상고객A", "900101-1234567", "[26201] 가상 컨퍼런스 매출", 100000000, 10000000),
]
FAKE_EINVOICE = [
    ["10-28", "C901", "(주)가상꽃", "일반", "[26299] 가상 꽃장식", 2000000, 200000, 2200000, "(도)외주비", "미지급금", None,
     "미처리"],
    ["10-20", "C101", "(주)가상음향", "일반", "[26201] 가상 컨퍼런스 음향", 40000000, 4000000, 44000000, "행사외주비(도)",
     "미지급금", None, "처리"],
]


def _jl(date, no, code, account, debit, credit, vendor, memo, vcode="V000"):
    return [serial(date) if isinstance(date, dt.date) else date, no, "대체", code, account, debit, credit, vendor,
            vcode, memo]


def _d(text):
    return dt.date(*[int(x) for x in text.split("-")])


def post(ledger):
    """매입 장부 줄마다 분개 3줄 + 다섯 가지 추가 전표를 만든다. 장부와 분개장이 서로 맞는다."""
    out = []
    for r in ledger:
        if r[0] != "매입":
            continue
        d, no, vendor, item = _d(r[1]), r[2], r[3], r[5]
        out.append(_jl(d, no, "61101", "행사외주비(도)", r[6], None, vendor, item, "V%03d" % no))
        out.append(_jl(d, no, "13500", "부가세대급금", r[7], None, vendor, item, "V%03d" % no))
        out.append(_jl(d, no, "25300", "미지급금", None, r[8], vendor, item, "V%03d" % no))
    out += [
        _jl(dt.date(2026, 10, 30), 20, "25300", "미지급금", 49500000, None, "주식회사 가상부스", "[26203] 가상 전시부스 지급"),
        _jl(dt.date(2026, 10, 30), 20, "10300", "보통예금", None, 49500000, "주식회사 가상부스", "[26203] 가상 전시부스 지급"),
        _jl(dt.date(2026, 10, 28), 21, "81900", "임차료", 3000000, None, "가상임대", "10월 임차료"),
        _jl(dt.date(2026, 10, 28), 21, "26200", "미지급비용", None, 3000000, "가상임대", "10월 임차료"),
        _jl(dt.date(2026, 10, 29), 22, "61101", "행사외주비(도)", 800000, None, "가상강사", "가상 개인강사 900101-1234567 강사료"),
        _jl(dt.date(2026, 10, 29), 22, "10300", "보통예금", None, 800000, "가상강사", "가상 개인강사 900101-1234567 강사료"),
        _jl(dt.date(2026, 10, 29), 23, "61101", "행사외주비(도)", 300000, None, "가상기타", "[26999] 가상 기타 행사"),
        _jl(dt.date(2026, 10, 29), 23, "10300", "보통예금", None, 300000, "가상기타", "[26999] 가상 기타 행사"),
        _jl(dt.date(2026, 10, 29), 24, "45100", "(도)외주비", 500000, None, "가상기타", "[26201] 계정 코드 4xxxx"),
        _jl(dt.date(2026, 10, 29), 24, "10300", "보통예금", None, 500000, "가상기타", "[26201] 계정 코드 4xxxx"),
    ]
    return out


FAKE_JOURNAL = post(FAKE_LEDGER)


def write_fake_books(folder, stamp="20261031", drop=(), journal=None, ledger=None, einvoice=None):
    """분개장·매입매출장·전자세금계산서(매입) 세 파일을 folder 에 쓴다. 장부만 주면 분개장은 그 장부에서 다시 만든다."""
    ledger = FAKE_LEDGER if ledger is None else ledger
    if journal is None:
        journal = FAKE_JOURNAL if ledger is FAKE_LEDGER else post(ledger)
    einvoice = FAKE_EINVOICE if einvoice is None else einvoice
    body = {"분개장": journal, "매입매출장": ledger, "전자세금계산서(매입)": einvoice}
    paths = {}
    os.makedirs(folder, exist_ok=True)
    for kind, header in KIND_FILES:
        if kind in drop:
            continue
        paths[kind] = write_xlsx(os.path.join(folder, "%s_%s.xlsx" % (kind, stamp)), [header] + [list(r) for r in body[kind]])
    return paths


_REQUESTS = []


def requests_all():
    """approval.build 가 만든 A['requests_all'] (가상 스냅숏 9건). 시험이 고쳐 써도 되게 복사본을 돌려준다."""
    if not _REQUESTS:
        tmp = tempfile.mkdtemp()
        try:
            snap = mod("snapshot").read_snapshot(write_fake_snapshot(tmp))
            A = mod("approval").build(mod("data").load(SAMPLE), snap, ASOF, NOW)
            _REQUESTS.append(A["requests_all"])
        finally:
            shutil.rmtree(tmp, True)
    return copy.deepcopy(_REQUESTS[0])


# ───────────── Task 1: 가상 엑셀 → 읽기 → 장부 → 요청 1201 ─────────────
class TestWehagoTracer(unittest.TestCase):
    def test_write_xlsx_makes_a_package_and_read_xlsx_reads_it(self):
        path = write_xlsx(os.path.join(new_tmp(self), "a.xlsx"), [["가", "나", 1], ["다", None, 44000000]])
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        for part in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
                     "xl/worksheets/sheet1.xml", "xl/sharedStrings.xml"):
            self.assertIn(part, names)
        self.assertEqual(mod("wehago").read_xlsx(path), [["가", "나", "1"], ["다", "", "44000000"]])

    def test_load_books_reads_three_synthetic_files(self):
        folder = os.path.join(new_tmp(self), "위하고")
        write_fake_books(folder)
        books = mod("wehago").load_books(folder, ASOF, 7)
        self.assertEqual((books.state, books.reason), ("ok", ""))
        self.assertEqual(books.book_date, dt.date(2026, 10, 31))
        self.assertEqual(books.files["분개장"]["last_date"], dt.date(2026, 10, 30))
        self.assertEqual(books.files["매입매출장"]["last_date"], dt.date(2026, 10, 27))
        self.assertEqual(books.files["전자세금계산서(매입)"]["last_date"], dt.date(2026, 10, 28))
        self.assertEqual(len(books.ledger), 8)  # 매출 줄은 남기지 않는다
        self.assertEqual(len(books.journal), 34)  # 8건 x 3줄 + 추가 전표 5건 x 2줄
        self.assertEqual(len(books.einvoice), 2)

    def test_request_1201_gets_its_status_from_the_books(self):
        w = mod("wehago")
        folder = os.path.join(new_tmp(self), "위하고")
        write_fake_books(folder)
        books = w.load_books(folder, ASOF, 7)
        reqs = requests_all()
        self.assertEqual([r["번호"] for r in reqs], [p[0] for p in FAKE_PAYMENTS])
        row = w.match_requests(books, reqs)["rows"]["1201"]
        self.assertEqual(row["status"], "계산서 있음")
        self.assertEqual((row["invoice_total"], row["diff"]), (44000000, 0))



# ───────────── Task 2: 읽기 단단하게 ─────────────
def folder_with(test, **kw):
    folder = os.path.join(new_tmp(test), "위하고")
    write_fake_books(folder, **kw)
    return folder


def load(folder, asof=ASOF, stale=7):
    return mod("wehago").load_books(folder, asof, stale)


def kind_path(folder, kind, stamp="20261031"):
    return os.path.join(folder, "%s_%s.xlsx" % (kind, stamp))


def read_kind(folder, kind, **kw):
    return mod("wehago").read_book(kind_path(folder, kind), kind, **kw)


def write_junk(path, data=b"not a zip"):
    with open(path, "wb") as f:
        f.write(data)
    return path


def all_rows(books):
    return books.journal + books.ledger + books.einvoice


class TestWehagoHeaders(unittest.TestCase):
    def test_real_header_forms_with_line_breaks_are_accepted(self):
        folder = folder_with(self)
        self.assertIn("11일\n이내", LEDGER_HEADER)
        self.assertIn("매입/매출\n유형", LEDGER_HEADER)
        rows, _ = read_kind(folder, "매입매출장")
        self.assertEqual(len(rows), 8)
        self.assertEqual(load(folder).state, "ok")

    def test_columns_in_another_order_read_the_same_rows(self):
        folder = folder_with(self)
        base, _ = read_kind(folder, "분개장")
        order = [9, 0, 1, 2, 3, 4, 5, 6, 7, 8]  # 적요를 맨 앞으로 (두 Code 열의 앞뒤 순서는 그대로)
        path = write_xlsx(os.path.join(new_tmp(self), "분개장_20261031.xlsx"),
                          [[r[i] for i in order] for r in [JOURNAL_HEADER] + FAKE_JOURNAL])
        moved, _ = mod("wehago").read_book(path, "분개장")
        self.assertEqual(moved, base)
        self.assertEqual(len(base), 34)

    def test_two_code_columns_map_by_order(self):
        rows, _ = read_kind(folder_with(self), "분개장")
        self.assertEqual(rows[0]["account_code"], "61101")
        self.assertNotIn("V001", repr(rows))  # 두 번째 Code(거래처 코드)는 쓰지 않는다

    def test_missing_column_stops_the_read_and_names_it(self):
        w = mod("wehago")
        folder = folder_with(self)
        drop = JOURNAL_HEADER.index("적요")
        write_xlsx(kind_path(folder, "분개장"),
                   [[c for i, c in enumerate(r) if i != drop] for r in [JOURNAL_HEADER] + FAKE_JOURNAL])
        with self.assertRaises(w.WehagoError) as cm:
            read_kind(folder, "분개장")
        self.assertIn("분개장", str(cm.exception))
        self.assertIn("없음: 적요", str(cm.exception))
        self.assertNotIn("추가", str(cm.exception))

    def test_renamed_column_is_missing_and_extra_and_load_books_stops(self):
        w = mod("wehago")
        folder = folder_with(self)
        header = [("메모" if h == "적요" else h) for h in JOURNAL_HEADER]
        write_xlsx(kind_path(folder, "분개장"), [header] + FAKE_JOURNAL)
        with self.assertRaises(w.WehagoError) as cm:
            read_kind(folder, "분개장")
        self.assertIn("추가: 메모", str(cm.exception))
        books = load(folder)
        self.assertEqual(books.state, "머리글 다름")
        self.assertEqual(books.reason, "분개장_20261031.xlsx 머리글이 예상과 다름 — 없음: 적요 · 추가: 메모")
        self.assertEqual(books.header, {"file": "분개장_20261031.xlsx", "kind": "분개장", "missing": ["적요"],
                                        "extra": ["메모"]})
        self.assertEqual((books.journal, books.ledger, books.einvoice), ([], [], []))

    def test_an_extra_column_alone_no_longer_stops(self):
        # D-35c 가 D-35a 의 '추가 열만으로도 멈춤'을 바꾼다: 필수 열이 다 있으면 읽고, 추가 열은 무시하되 알린다.
        folder = folder_with(self)
        write_xlsx(kind_path(folder, "매입매출장"), [LEDGER_HEADER + ["비고"]] + [r + ["x"] for r in FAKE_LEDGER])
        books = load(folder)
        self.assertEqual((books.state, books.reason), ("ok", ""))
        self.assertEqual(len(books.ledger), 8)
        self.assertEqual(books.files["매입매출장"]["extra_columns"], ["비고"])
        self.assertEqual(books.files["매입매출장"]["extra_note"], "추가 열 무시: 비고")

    def test_header_mismatch_wins_over_a_missing_file(self):
        folder = folder_with(self, drop=("전자세금계산서(매입)",))
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER[:-1]] + [r[:-1] for r in FAKE_JOURNAL])
        self.assertEqual(load(folder).state, "머리글 다름")


class TestWehagoCells(unittest.TestCase):
    def xlsx(self, rows, **kw):
        return write_xlsx(os.path.join(new_tmp(self), "a.xlsx"), rows, **kw)

    def test_first_sheet_is_found_through_workbook_and_rels(self):
        path = self.xlsx([["첫", "시트"], ["1", "2"]], first_part="sheet2.xml", extra_sheet=[["다른", "줄"], ["9", "9"]])
        self.assertEqual(mod("wehago").read_xlsx(path), [["첫", "시트"], ["1", "2"]])

    def test_rich_text_inline_and_formula_string_cells(self):
        w = mod("wehago")
        path = self.xlsx([[("rich", ["가", "상", " 글"]), ("inline", "인라인"), ("str", "수식 글")]])
        self.assertEqual(w.read_xlsx(path), [["가상 글", "인라인", "수식 글"]])
        path = self.xlsx([["모두", "인라인"]], inline=True)
        self.assertEqual(w.read_xlsx(path), [["모두", "인라인"]])

    def test_sparse_and_r_less_cells_land_in_the_right_columns(self):
        w = mod("wehago")
        self.assertEqual(w.read_xlsx(self.xlsx([["a", None, "c"]])), [["a", "", "c"]])
        raw = (_XML + '<worksheet xmlns="%s"><sheetData><row r="1"><c><v>1</v></c><c><v>2</v></c></row>'
               '<row r="2"><c r="C2"><v>3</v></c><c><v>4</v></c></row></sheetData></worksheet>' % _MAIN)
        self.assertEqual(w.read_xlsx(self.xlsx([], raw_sheet_xml=raw)), [["1", "2", "", ""], ["", "", "3", "4"]])

    def test_error_and_boolean_cells_read_as_empty(self):
        w = mod("wehago")
        path = self.xlsx([[("e", "#REF!"), ("b", "1"), 5]])
        self.assertEqual(w.read_xlsx(path), [["", "", "5"]])

    def ledger_total(self, cell):
        folder = folder_with(self)
        row = list(FAKE_LEDGER[0])
        row[8] = cell
        write_xlsx(kind_path(folder, "매입매출장"), [LEDGER_HEADER, row])
        return read_kind(folder, "매입매출장")[0][0]["total"]

    def test_amount_forms(self):
        self.assertEqual(self.ledger_total(("n", "4.4E7")), 44000000)
        self.assertEqual(self.ledger_total("44,000,000"), 44000000)
        self.assertEqual(self.ledger_total(44000000), 44000000)
        self.assertIsNone(self.ledger_total(""))
        self.assertIsNone(self.ledger_total(None))
        self.assertIsNone(self.ledger_total(("n", "1.5")))
        self.assertIsNone(self.ledger_total(("e", "#REF!")))
        self.assertIsNone(self.ledger_total("가격 미정"))

    def test_error_cell_in_debit_reads_as_none_not_zero(self):
        folder = folder_with(self)
        row = list(FAKE_JOURNAL[0])
        row[5] = ("e", "#REF!")
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER, row])
        self.assertIsNone(read_kind(folder, "분개장")[0][0]["debit"])

    def journal_date(self, cell, **kw):
        folder = folder_with(self)
        row = list(FAKE_JOURNAL[0])
        row[0] = cell
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER, row], **kw)
        return read_kind(folder, "분개장")[0][0]["date"]

    def test_date_forms(self):
        want = dt.date(2026, 10, 20)
        self.assertEqual(self.journal_date(46315), want)
        self.assertEqual(self.journal_date(46315.5), want)
        self.assertEqual(self.journal_date(44853, date1904=True), want)
        for text in ("2026-10-20", "2026.10.20", "2026/10/20", "20261020"):
            self.assertEqual(self.journal_date(text), want, text)
        self.assertEqual(self.journal_date(20261020), want)
        self.assertIsNone(self.journal_date("abc"))

    def test_einvoice_month_day_takes_the_file_year(self):
        folder = folder_with(self)
        rows = [list(r) for r in FAKE_EINVOICE]
        rows[0][0], rows[1][0] = "10-28", "12-30"
        write_xlsx(kind_path(folder, "전자세금계산서(매입)"), [EINVOICE_HEADER] + rows)
        got, _ = read_kind(folder, "전자세금계산서(매입)", file_date=dt.date(2026, 10, 31))
        self.assertEqual([r["date"] for r in got], [dt.date(2026, 10, 28), dt.date(2025, 12, 30)])

    def test_subtotal_and_blank_rows_are_skipped_and_counted(self):
        folder = folder_with(self)
        extra = [["", "", "", "", "월계", 1000, 1000, "", "", ""],
                 ["", "", "", "", "", "", "", "", "", "누계"],
                 [None] * 10]
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER] + FAKE_JOURNAL + extra)
        books = load(folder)
        self.assertEqual(books.state, "ok")
        self.assertEqual(len(books.journal), 34)
        self.assertEqual(books.files["분개장"]["skipped"], 3)
        self.assertEqual(books.files["분개장"]["last_date"], dt.date(2026, 10, 30))

    def test_undated_data_row_is_kept_and_counted(self):
        folder = folder_with(self)
        row = list(FAKE_JOURNAL[0])
        row[0] = "abc"
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER] + FAKE_JOURNAL + [row])
        books = load(folder)
        self.assertEqual(len(books.journal), 35)
        self.assertIsNone(books.journal[-1]["date"])
        self.assertEqual((books.files["분개장"]["undated"], books.files["분개장"]["skipped"]), (1, 0))
        self.assertEqual(books.files["분개장"]["last_date"], dt.date(2026, 10, 30))


class TestWehagoFolder(unittest.TestCase):
    def test_newest_file_date_wins_and_the_other_is_unused(self):
        folder = folder_with(self)
        write_fake_books(folder, stamp="20261024", drop=("매입매출장", "전자세금계산서(매입)"))
        books = load(folder)
        self.assertEqual(books.state, "ok")
        self.assertEqual(books.files["분개장"]["name"], "분개장_20261031.xlsx")
        self.assertEqual(books.unused, ["분개장_20261024.xlsx"])

    def test_excel_owner_file_is_ignored_even_when_newest(self):
        folder = folder_with(self)
        junk = write_junk(os.path.join(folder, "~$분개장_20261031.xlsx"), b"\x00junk")
        later = time.time() + 1000
        os.utime(junk, (later, later))
        books = load(folder)
        self.assertEqual(books.state, "ok")
        self.assertEqual(books.files["분개장"]["name"], "분개장_20261031.xlsx")
        self.assertNotIn("~$", repr(books.files) + repr(books.unused) + books.reason)

    def test_sales_einvoice_export_is_never_read_as_purchase(self):
        folder = folder_with(self)
        sales = [list(r) for r in FAKE_EINVOICE]
        sales[0][2] = "(주)가상음향"
        sales[0][7] = 777
        write_xlsx(os.path.join(folder, "전자세금계산서(매출)_20261031.xlsx"), [EINVOICE_HEADER] + sales)
        books = load(folder)
        self.assertEqual(books.state, "ok")
        self.assertEqual(books.files["전자세금계산서(매입)"]["name"], "전자세금계산서(매입)_20261031.xlsx")
        self.assertEqual(books.unused, ["전자세금계산서(매출)_20261031.xlsx"])
        self.assertEqual(len(books.einvoice), 2)
        self.assertNotIn(777, [r["total"] for r in books.einvoice])

    def test_xls_look_alike_is_named_in_the_missing_reason(self):
        folder = folder_with(self, drop=("분개장",))
        write_junk(os.path.join(folder, "분개장_20261031.xls"), b"\xd0\xcf\x11\xe0")
        books = load(folder)
        self.assertEqual(books.state, "자료 없음")
        self.assertIn("분개장", books.reason)
        self.assertIn(".xlsx만 읽음 (분개장_20261031.xls 있음)", books.reason)
        self.assertEqual((books.journal, books.ledger, books.einvoice), ([], [], []))

    def test_missing_files_are_named(self):
        empty = os.path.join(new_tmp(self), "비어 있음")
        os.makedirs(empty)
        books = load(empty)
        self.assertEqual(books.state, "자료 없음")
        for kind in ("분개장", "매입매출장", "전자세금계산서(매입)"):
            self.assertIn(kind, books.reason)
        only = folder_with(self, drop=("매입매출장", "전자세금계산서(매입)"))
        books = load(only)
        self.assertEqual(books.state, "자료 없음")
        self.assertIn("매입매출장", books.reason)
        self.assertIn("전자세금계산서(매입)", books.reason)
        self.assertEqual(load(os.path.join(empty, "없는 폴더")).state, "자료 없음")

    def test_stale_books_stop_the_cross_check(self):
        books = load(folder_with(self, stamp="20261025"))
        self.assertEqual(books.state, "경과")
        self.assertIn("2026-10-25", books.reason)
        self.assertIn("8일", books.reason)
        self.assertEqual((books.journal, books.ledger, books.einvoice), ([], [], []))
        self.assertEqual(books.book_date, dt.date(2026, 10, 25))
        self.assertEqual(load(folder_with(self, stamp="20261026")).state, "ok")

    def test_missing_wins_over_stale(self):
        self.assertEqual(load(folder_with(self, stamp="20261025", drop=("분개장",))).state, "자료 없음")

    def test_ref_date_falls_back_to_the_last_row_date(self):
        folder = folder_with(self)
        os.rename(kind_path(folder, "분개장"), os.path.join(folder, "분개장.xlsx"))
        books = load(folder)
        self.assertEqual(books.state, "ok")
        self.assertEqual(books.files["분개장"]["file_date"], None)
        self.assertEqual(books.files["분개장"]["ref_date"], dt.date(2026, 10, 30))
        self.assertEqual(books.book_date, dt.date(2026, 10, 30))

    def test_not_a_zip_is_a_read_failure(self):
        folder = folder_with(self)
        write_junk(kind_path(folder, "분개장"))
        books = load(folder)
        self.assertEqual(books.state, "읽기 실패")
        self.assertIn("엑셀 파일을 열 수 없음", books.reason)
        self.assertIn("분개장_20261031.xlsx", books.reason)
        self.assertEqual((books.journal, books.ledger, books.einvoice), ([], [], []))

    def test_doctype_in_a_part_is_refused_before_parsing(self):
        folder = folder_with(self)
        bad = (_XML + '<!DOCTYPE worksheet [<!ENTITY a "b">]><worksheet xmlns="%s"><sheetData/></worksheet>' % _MAIN)
        write_xlsx(kind_path(folder, "분개장"), [], raw_sheet_xml=bad)
        books = load(folder)
        self.assertEqual(books.state, "읽기 실패")
        self.assertIn("엑셀 내부 형식이 예상과 다름", books.reason)

    def test_oversized_part_is_refused(self):
        w = mod("wehago")
        folder = folder_with(self)
        with mock.patch.object(w, "MAX_PART_BYTES", 1000):
            books = w.load_books(folder, ASOF, 7)
        self.assertEqual(books.state, "읽기 실패")
        self.assertIn("엑셀 파일이 너무 큼", books.reason)

    def test_broken_xml_is_a_read_failure(self):
        folder = folder_with(self)
        write_xlsx(kind_path(folder, "분개장"), [], raw_sheet_xml=_XML + "<worksheet><sheetData><row>")
        books = load(folder)
        self.assertEqual(books.state, "읽기 실패")
        self.assertIn("엑셀 내부 형식이 예상과 다름", books.reason)

    def test_read_failure_wins_over_stale(self):
        folder = folder_with(self, stamp="20261025")
        write_junk(kind_path(folder, "분개장", "20261025"))
        self.assertEqual(load(folder).state, "읽기 실패")


class TestWehagoPrivacy(unittest.TestCase):
    def test_mask_rrn(self):
        m = mod("wehago").mask_rrn
        star = "******-*******"
        self.assertEqual(m("가상 개인강사 900101-1234567 강사료"), "가상 개인강사 %s 강사료" % star)
        self.assertEqual(m("9001011234567"), star)
        self.assertEqual(m("900101-0234567"), star)
        self.assertEqual(m("900101-9234567"), star)
        self.assertEqual(m("900101 9234567"), star)
        self.assertEqual(m("123-45-67890"), "123-45-67890")
        self.assertEqual(m("12900101-1234567"), "12" + star)
        self.assertEqual(m(""), "")

    def test_mask_rrn_other_spellings(self):
        """WR-08: 구분자 앞뒤 공백, 여러 대시(‐ ‑ ‒ – — ― － −), 점, 빗금도 가린다. util 과 wehago 는 같은 함수."""
        self.assertIs(mod("wehago").mask_rrn, mod("util").mask_rrn)
        m = mod("util").mask_rrn
        star = "******-*******"
        for text in ("800101 - 1234567", "800101  1234567", "800101 -1234567", "800101- 1234567",
                     "800101‐1234567", "800101‑1234567", "800101‒1234567", "800101–1234567", "800101—1234567",
                     "800101―1234567", "800101－1234567", "800101−1234567", "800101.1234567", "800101 . 1234567",
                     "800101/1234567", "800101 / 1234567", "８００１０１－１２３４５６７", "800101．1234567"):
            self.assertEqual(m("강사료 홍길동 %s 지급" % text), "강사료 홍길동 %s 지급" % star, text)

    def test_mask_rrn_keeps_ordinary_amounts_dates_and_phone_numbers(self):
        m = mod("util").mask_rrn
        for text in ("2026-10-31", "2026.10.31", "2026/10/31", "2026-11-02 15:52:03", "20261031", "165,000,000",
                     "165000000", "−44,000,000", "010-1234-5678", "02-123-4567", "123-45-67890", "[26201] 가상 행사",
                     "분개장_20261031.xlsx", "금액 차이 (계산서 165,000,000 · 차액 +4,500,000)"):
            self.assertEqual(m(text), text, text)
        self.assertEqual(m(None), "")

    def test_no_rrn_survives_loading_and_the_biz_number_column_is_not_stored(self):
        books = load(folder_with(self))
        self.assertEqual(books.state, "ok")
        for row in books.ledger:
            self.assertFalse([k for k in row if "사업자" in k or "주민" in k])
            self.assertNotIn("000-00-0000", repr(row))
        text = repr(all_rows(books))
        self.assertNotIn("900101-1234567", text)
        self.assertNotIn("9001011234567", text)
        memos = [r["memo"] for r in books.journal if "강사료" in r["memo"]]
        self.assertEqual(memos, ["가상 개인강사 ******-******* 강사료"] * 2)

    def test_rrn_in_the_vendor_and_item_columns_is_masked_too(self):
        folder = folder_with(self)
        row = list(FAKE_LEDGER[0])
        row[3], row[5] = "개인 900101-1234567", "[26201] 900101 1234567 강의"
        write_xlsx(kind_path(folder, "매입매출장"), [LEDGER_HEADER, row])
        got = read_kind(folder, "매입매출장")[0][0]
        self.assertEqual(got["vendor"], "개인 ******-*******")
        self.assertEqual(got["item"], "[26201] ******-******* 강의")



# ───────────── Task 3: 대조 엔진 ─────────────
def label(m, no):
    return m["rows"][no]["label"]


def with_journal(test, extra=(), edit=None, **kw):
    """FAKE_JOURNAL 을 고쳐 장부를 쓰고 읽는다 (edit(줄) 은 줄을 새로 돌려준다)."""
    journal = [edit(list(r)) if edit else list(r) for r in FAKE_JOURNAL] + [list(r) for r in extra]
    return load(folder_with(test, journal=journal, **kw))


def pay_line(no=25, date=dt.date(2026, 10, 30), amount=49500000, vendor="주식회사 가상부스", memo="[26203] 가상 전시부스 지급"):
    return _jl(date, no, "25300", "미지급금", amount, None, vendor, memo)


class TestWehagoMatch(unittest.TestCase):
    def setUp(self):
        self.w = mod("wehago")
        self.books = load(folder_with(self))
        self.reqs = requests_all()
        self.m = self.w.match_requests(self.books, self.reqs)

    def test_the_nine_labels(self):
        want = {
            "1201": "계산서 있음",
            "5102": "계산서 없음",
            "5103": "금액 차이 (계산서 165,000,000 · 차액 +4,500,000)",
            "5104": "계산서 있음",
            "5105": "연결 불가 (계산서 후보 2건)",
            "5106": "연결 불가 (금액 미확인)",
            "5107": "연결 불가 (거래처 후보 0건)",
            "5108": "계산서 있음 (전자세금계산서)",
            "5109": "이미 지급 (분개장 2026-10-30 전표 20)",
        }
        self.assertEqual(dict((no, label(self.m, no)) for no in want), want)
        status = dict((no, self.m["rows"][no]["status"]) for no in want)
        self.assertEqual(status, {"1201": "계산서 있음", "5102": "계산서 없음", "5103": "금액 차이", "5104": "계산서 있음",
                                  "5105": "연결 불가", "5106": "연결 불가", "5107": "연결 불가", "5108": "계산서 있음",
                                  "5109": "이미 지급"})

    def test_row_fields(self):
        r = self.m["rows"]
        self.assertEqual((r["5103"]["invoice_total"], r["5103"]["diff"]), (165000000, 4500000))
        self.assertEqual((r["1201"]["invoice_total"], r["1201"]["diff"], r["1201"]["source"]), (44000000, 0, "매입매출장"))
        self.assertEqual(r["5108"]["source"], "전자세금계산서(매입)")
        self.assertEqual(r["5105"]["candidates"], 2)
        self.assertEqual(r["5109"]["payment"], {"date": dt.date(2026, 10, 30), "no": "20", "amount": 49500000})
        self.assertIsNone(r["1201"]["payment"])

    def test_schedule_amount_uses_the_wehago_total_only_for_amount_differences(self):
        r = self.m["rows"]
        self.assertEqual(r["5103"]["schedule_amount"], 165000000)  # D-30a
        self.assertEqual(r["1201"]["schedule_amount"], 44000000)
        self.assertEqual(r["5105"]["schedule_amount"], 3300000)
        self.assertIsNone(r["5106"]["schedule_amount"])

    def test_one_combined_invoice_turns_5105_into_an_amount_difference(self):
        led = [r for r in FAKE_LEDGER if r[2] not in (7, 8)]
        led.append(_L("매입", "2026-10-25", 7, "(주) 가상버스", "000-00-00006", "[26221] 가상 워크숍 버스", 3300000, 330000))
        m = self.w.match_requests(load(folder_with(self, ledger=led)), self.reqs)
        self.assertEqual(label(m, "5105"), "금액 차이 (계산서 3,630,000 · 차액 +330,000)")
        self.assertEqual(m["rows"]["5105"]["schedule_amount"], 3630000)

    def test_summary(self):
        S = self.m["summary"]
        for status in ("계산서 있음", "금액 차이", "계산서 없음", "이미 지급", "연결 불가", "판단 불가"):
            self.assertIn(status, S)
        self.assertEqual((S["계산서 있음"]["count"], S["계산서 있음"]["sum"], S["계산서 있음"]["unknown"]), (3, 51700000, 0))
        d = S["금액 차이"]
        self.assertEqual((d["count"], d["sum"], d["invoice_sum"], d["diff"]), (1, 160500000, 165000000, 4500000))
        self.assertEqual((S["계산서 없음"]["count"], S["계산서 없음"]["sum"]), (1, 264000))
        self.assertEqual((S["이미 지급"]["count"], S["이미 지급"]["sum"]), (1, 49500000))
        c = S["연결 불가"]
        self.assertEqual((c["count"], c["sum"], c["unknown"]), (3, 4400000, 1))
        self.assertEqual(S["판단 불가"]["count"], 0)

    def test_an_all_unknown_status_has_no_sum_instead_of_zero(self):
        only = [r for r in self.reqs if r["번호"] == "5106"]
        S = self.w.match_requests(self.books, only)["summary"]
        self.assertEqual((S["연결 불가"]["count"], S["연결 불가"]["sum"], S["연결 불가"]["unknown"]), (1, None, 1))

    def test_norm_vendor(self):
        for name in ("(주)가상음향", "㈜가상음향", "주식회사 가상음향", "가상 음향", "가상음향(주)"):
            self.assertEqual(self.w.norm_vendor(name), "가상음향", name)

    def test_result_does_not_depend_on_request_order_and_nothing_is_mutated(self):
        before = (copy.deepcopy(self.reqs), copy.deepcopy(self.books.__dict__))
        again = self.w.match_requests(self.books, list(reversed(self.reqs)))
        self.assertEqual(again, self.m)
        self.assertEqual((self.reqs, self.books.__dict__), before)

    def test_two_payment_lines_make_the_payment_doubtful(self):
        books = with_journal(self, extra=[pay_line()])
        m = self.w.match_requests(books, self.reqs)
        self.assertEqual(label(m, "5109"), "연결 불가 (지급 후보 2건)")
        self.assertNotEqual(m["rows"]["5109"]["status"], "이미 지급")

    def test_payment_dated_before_registration_is_not_a_payment(self):
        def earlier(r):
            if r[1] == 20:
                r[0] = serial(dt.date(2026, 10, 28))  # 5109 등록일(10-29)보다 앞
            return r
        m = self.w.match_requests(with_journal(self, edit=earlier), self.reqs)
        self.assertEqual(label(m, "5109"), "계산서 있음")

    def test_payment_must_carry_the_same_project_code(self):
        def other_code(r):
            if r[1] == 20:
                r[9] = "[26299] 다른 행사 지급"
            return r
        self.assertNotEqual(self.w.match_requests(with_journal(self, edit=other_code), self.reqs)["rows"]["5109"]["status"],
                            "이미 지급")

        def no_code(r):
            if r[1] == 20:
                r[9] = "지급"
            return r
        m = self.w.match_requests(with_journal(self, edit=no_code), self.reqs)
        self.assertEqual(label(m, "5109"), "이미 지급 (분개장 2026-10-30 전표 20)")

    def test_payment_must_be_on_a_payable_account(self):
        def bank(r):
            if r[1] == 20 and r[4] == "미지급금":
                r[4] = "보통예금"
            return r
        self.assertNotEqual(self.w.match_requests(with_journal(self, edit=bank), self.reqs)["rows"]["5109"]["status"],
                            "이미 지급")

    def test_one_payment_line_cannot_pay_two_requests(self):
        twin = copy.deepcopy([r for r in self.reqs if r["번호"] == "5109"][0])
        twin["번호"], twin["id"] = "5113", "r99"
        m = self.w.match_requests(self.books, self.reqs + [twin])
        for no in ("5109", "5113"):
            self.assertEqual(m["rows"][no]["status"], "연결 불가", no)
            self.assertTrue(label(m, no).startswith("연결 불가 (지급 후보"), no)

    def test_one_invoice_cannot_match_two_requests(self):
        twin = copy.deepcopy([r for r in self.reqs if r["번호"] == "1201"][0])
        twin["번호"], twin["id"] = "5112", "r99"
        m = self.w.match_requests(self.books, self.reqs + [twin])
        self.assertEqual(label(m, "1201"), "연결 불가 (계산서 후보 공유)")
        self.assertEqual(label(m, "5112"), "연결 불가 (계산서 후보 공유)")
        self.assertEqual(label(m, "5104"), "계산서 있음")

    def test_books_that_are_not_ok_make_every_request_undecidable(self):
        cases = (("경과", dict(stamp="20261025"), "판단 불가(WEHAGO 자료 경과)"),
                 ("자료 없음", dict(drop=("분개장",)), "판단 불가(WEHAGO 자료 없음)"))
        for state, kw, text in cases:
            books = load(folder_with(self, **kw))
            self.assertEqual(books.state, state)
            m = self.w.match_requests(books, self.reqs)
            self.assertEqual(set(r["label"] for r in m["rows"].values()), set([text]))
            self.assertEqual(set(r["status"] for r in m["rows"].values()), set(["판단 불가"]))
            for rq in self.reqs:
                self.assertEqual(m["rows"][rq["번호"]]["schedule_amount"], rq["amount"])
            self.assertEqual(m["summary"]["판단 불가"]["count"], 9)
            self.assertEqual(m["summary"]["이미 지급"]["count"], 0)

    def test_header_mismatch_and_read_failure_labels(self):
        folder = folder_with(self)
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER[:-1]] + [r[:-1] for r in FAKE_JOURNAL])
        m = self.w.match_requests(load(folder), self.reqs)
        self.assertEqual(set(r["label"] for r in m["rows"].values()), set(["판단 불가(머리글 다름)"]))
        folder = folder_with(self)
        write_junk(kind_path(folder, "분개장"))
        m = self.w.match_requests(load(folder), self.reqs)
        self.assertEqual(set(r["label"] for r in m["rows"].values()), set(["판단 불가(WEHAGO 읽기 실패)"]))
        self.assertFalse([1 for r in m["rows"].values() if r["status"] == "이미 지급"])


class TestWehagoPayables(unittest.TestCase):
    def setUp(self):
        self.w = mod("wehago")
        self.books = load(folder_with(self))
        self.reqs = requests_all()
        self.m = self.w.match_requests(self.books, self.reqs)
        self.P = self.w.vendor_payables(self.books, self.reqs, self.m)

    def row(self, r):
        return (r["vendor"], r["payable"], r["requested"], r["diff"])

    def test_the_d33_truth(self):
        P = self.P
        self.assertEqual((P["compared"], P["diff_count"], P["diff_sum"], P["unknown_count"]), (9, 6, 10976000, 1))
        self.assertEqual((P["opening"], P["note"]), (False, "기초잔액 미반영"))
        self.assertEqual(len(P["rows"]), 7)
        rows = [self.row(r) for r in P["rows"]]
        self.assertEqual(rows[:3], [("㈜가상제작", 165000000, 160500000, 4500000), ("가상임대", 3000000, 0, 3000000),
                                    ("(주) 가상버스", 5940000, 3300000, 2640000)])
        self.assertEqual(rows[3:6], [("가상꽃", 0, 2200000, -2200000), ("가상인력", 7700000, 5500000, 2200000),
                                     ("가상 조명", 1100000, 264000, 836000)])
        last = P["rows"][6]
        self.assertEqual((last["vendor"], last["diff"], last["requested"], last["requested_unknown"]),
                         ("가상숙박", None, None, 1))

    def test_status_unknown_and_already_paid_requests_are_not_counted(self):
        names = [r["vendor"] for r in self.P["rows"]]
        self.assertNotIn("가상케이터링", names)  # 5107: 상태 확인 필요
        self.assertNotIn("가상부스", names)
        self.assertNotIn("주식회사 가상부스", names)  # 5109 는 이미 지급이고 미지급금도 0

    def test_opening_balance_line_removes_the_label(self):
        opening = _jl(dt.date(2026, 1, 2), 0, "25300", "미지급금", None, 1000000, "가상임대", "전기이월")
        books = with_journal(self, extra=[opening])
        P = self.w.vendor_payables(books, self.reqs, self.w.match_requests(books, self.reqs))
        self.assertEqual((P["opening"], P["note"]), (True, ""))
        rent = [r for r in P["rows"] if r["vendor"] == "가상임대"][0]
        self.assertEqual((rent["payable"], rent["diff"]), (4000000, 4000000))
        self.assertEqual(P["diff_sum"], 11976000)

    def test_opening_text_on_a_non_payable_line_does_not_count(self):
        other = _jl(dt.date(2026, 1, 2), 0, "10300", "보통예금", 1000000, None, "가상임대", "전기이월")
        books = with_journal(self, extra=[other])
        self.assertFalse(self.w.vendor_payables(books, self.reqs, self.w.match_requests(books, self.reqs))["opening"])

    def test_books_that_are_not_ok_give_no_rows(self):
        books = load(folder_with(self, stamp="20261025"))
        P = self.w.vendor_payables(books, self.reqs, self.w.match_requests(books, self.reqs))
        self.assertEqual((P["rows"], P["compared"], P["diff_count"], P["unknown_count"]), ([], 0, 0, 0))

    def test_inputs_are_not_changed(self):
        before = (copy.deepcopy(self.reqs), copy.deepcopy(self.books.__dict__), copy.deepcopy(self.m))
        self.w.vendor_payables(self.books, self.reqs, self.m)
        self.assertEqual((self.reqs, self.books.__dict__, self.m), before)


class TestWehagoProjectCost(unittest.TestCase):
    KEYS = set(["26201", "26220", "26221", "26203"])

    def setUp(self):
        self.w = mod("wehago")
        self.books = load(folder_with(self))

    def test_the_d34_truth(self):
        pc = self.w.project_costs(self.books, self.KEYS)
        self.assertEqual(dict((k, v["cost"]) for k, v in pc["by_code"].items()),
                         {"26201": 40000000, "26220": 158000000, "26221": 5400000, "26203": 45000000})
        self.assertEqual((pc["unlinked"]["count"], pc["unlinked"]["sum"]), (2, 1100000))
        lines = [(l["date"], l["vendor"], l["memo"], l["amount"]) for l in pc["unlinked"]["lines"]]
        self.assertEqual(lines, [(dt.date(2026, 10, 29), "가상강사", "가상 개인강사 ******-******* 강사료", 800000),
                                 (dt.date(2026, 10, 29), "가상기타", "[26999] 가상 기타 행사", 300000)])
        self.assertEqual(len(pc["by_code"]["26220"]["lines"]), 4)

    def test_account_code_starting_with_4_is_not_cost(self):
        pc = self.w.project_costs(self.books, self.KEYS)
        every = [l["amount"] for v in pc["by_code"].values() for l in v["lines"]] + \
                [l["amount"] for l in pc["unlinked"]["lines"]]
        self.assertNotIn(500000, every)

    def test_credit_lines_reduce_cost(self):
        credit = _jl(dt.date(2026, 10, 29), 30, "61101", "행사외주비(도)", None, 1000000, "가상음향", "[26201] 환불")
        books = with_journal(self, extra=[credit])
        self.assertEqual(self.w.project_costs(books, self.KEYS)["by_code"]["26201"]["cost"], 39000000)

    def test_a_line_with_no_amount_is_counted_not_zeroed(self):
        blank = _jl(dt.date(2026, 10, 29), 31, "61101", "행사외주비(도)", None, None, "가상음향", "[26201] 금액 없음")
        books = with_journal(self, extra=[blank])
        pc = self.w.project_costs(books, self.KEYS)
        self.assertEqual(pc["by_code"]["26201"]["cost"], 40000000)
        self.assertEqual(pc["by_code"]["26201"]["unknown"], 1)

    def test_books_that_are_not_ok_give_nothing(self):
        books = load(folder_with(self, stamp="20261025"))
        pc = self.w.project_costs(books, self.KEYS)
        self.assertEqual((pc["by_code"], pc["unlinked"]["count"], pc["unlinked"]["lines"]), ({}, 0, []))


if __name__ == "__main__":
    unittest.main()


# ───────────── D-35c: 실제 파일 점검 후속 (추가 열 · 요약 줄 · 장부 기준일 이후 전표) ─────────────
REAL_EXTRA = ["Code", "계정과목", "Code", "부서명", "Code", "프로젝트명", "Code", "카드사명"]


class TestWehagoExtraColumns(unittest.TestCase):
    def test_real_ledger_header_with_eight_more_columns_loads(self):
        folder = folder_with(self)
        base, _ = read_kind(folder, "매입매출장")
        rows = [LEDGER_HEADER + REAL_EXTRA] + [r + ["1", "미지급금", "2", "영업", "3", "", "4", ""] for r in FAKE_LEDGER]
        write_xlsx(kind_path(folder, "매입매출장"), rows)
        got, info = read_kind(folder, "매입매출장")
        self.assertEqual(got, base)
        self.assertEqual(info["extra_columns"], REAL_EXTRA)
        books = load(folder)
        self.assertEqual((books.state, books.reason), ("ok", ""))
        entry = books.files["매입매출장"]
        self.assertEqual(entry["extra_columns"], REAL_EXTRA)
        self.assertEqual(entry["extra_note"], "추가 열 무시: " + ", ".join(REAL_EXTRA))
        self.assertEqual(books.files["분개장"]["extra_columns"], [])
        self.assertEqual(books.files["분개장"]["extra_note"], "")
        self.assertEqual(len(books.ledger), 8)

    def test_extra_columns_between_required_ones_are_ignored(self):
        folder = folder_with(self)
        base, _ = read_kind(folder, "매입매출장")
        rows = [r[:3] + ["끼움A"] + r[3:8] + ["끼움B"] + r[8:] for r in [LEDGER_HEADER] + FAKE_LEDGER]
        rows[0][3], rows[0][9] = "끼움A", "끼움B"
        write_xlsx(kind_path(folder, "매입매출장"), rows)
        got, info = read_kind(folder, "매입매출장")
        self.assertEqual(got, base)
        self.assertEqual(info["extra_columns"], ["끼움A", "끼움B"])

    def test_the_two_leading_code_columns_of_the_journal_still_map_by_order(self):
        folder = folder_with(self)
        base, _ = read_kind(folder, "분개장")
        rows = [r + ["Z"] for r in [JOURNAL_HEADER] + FAKE_JOURNAL]
        rows[0][-1] = "Code"  # 세 번째 Code 는 추가 열
        write_xlsx(kind_path(folder, "분개장"), rows)
        got, info = read_kind(folder, "분개장")
        self.assertEqual(got, base)
        self.assertEqual(got[0]["account_code"], "61101")
        self.assertEqual(info["extra_columns"], ["Code"])

    def test_a_missing_required_column_still_stops_even_with_extra_columns(self):
        folder = folder_with(self)
        drop = LEDGER_HEADER.index("합계")
        rows = [[c for i, c in enumerate(r) if i != drop] + ["비고"] for r in [LEDGER_HEADER] + FAKE_LEDGER]
        write_xlsx(kind_path(folder, "매입매출장"), rows)
        books = load(folder)
        self.assertEqual(books.state, "머리글 다름")
        self.assertIn("없음: 합계", books.reason)
        self.assertEqual((books.journal, books.ledger, books.einvoice), ([], [], []))


class TestWehagoSummaryRows(unittest.TestCase):
    TOTAL = "합계 (건수 : 4,292 )"
    BY_VENDOR = "거래처별 소계: 9건"
    GROUP = "합계(거래처:166) : 753건"

    def test_journal_total_in_the_date_column_is_skipped_not_undated(self):
        folder = folder_with(self)
        total = [self.TOTAL] + [""] * 9
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER] + FAKE_JOURNAL + [total])
        books = load(folder)
        entry = books.files["분개장"]
        self.assertEqual((entry["skipped"], entry["undated"], entry["rows"]), (1, 0, 34))
        self.assertEqual(len(books.journal), 34)
        self.assertEqual(entry["last_date"], dt.date(2026, 10, 30))

    def test_einvoice_vendor_subtotal_and_ledger_group_total(self):
        folder = folder_with(self)
        sub = [self.BY_VENDOR] + [""] * 11
        write_xlsx(kind_path(folder, "전자세금계산서(매입)"), [EINVOICE_HEADER] + FAKE_EINVOICE + [sub])
        grp = [""] * 14
        grp[3] = "  " + self.GROUP + " "
        write_xlsx(kind_path(folder, "매입매출장"), [LEDGER_HEADER] + FAKE_LEDGER + [grp])
        books = load(folder)
        self.assertEqual(books.state, "ok")
        for kind, n in (("전자세금계산서(매입)", 2), ("매입매출장", 9)):
            entry = books.files[kind]
            self.assertEqual((entry["skipped"], entry["undated"], entry["rows"]), (1, 0, n), kind)
        self.assertEqual(books.files["전자세금계산서(매입)"]["last_date"], dt.date(2026, 10, 28))
        self.assertEqual(len(books.einvoice), 2)
        self.assertEqual(len(books.ledger), 8)

    def test_spaced_and_period_totals_in_the_ledger_date_column_are_skipped(self):
        # 실제 매입매출장: 전표일자 칸에 '합       계'처럼 글자 사이 공백, '분기 누계'·'반기 누계', 구분은 '매입', 금액도 있음 (D-35c)
        folder = folder_with(self)
        extra = []
        for text in ("합       계", "월       계", "누       계", "분기 누계", "반기 누계"):
            row = ["매입", text, "", "", "", "", "1,000", "100", "1,100", "", "", "", "", ""]
            extra.append(row)
        write_xlsx(kind_path(folder, "매입매출장"), [LEDGER_HEADER] + FAKE_LEDGER + extra)
        books = load(folder)
        entry = books.files["매입매출장"]
        self.assertEqual((entry["skipped"], entry["undated"]), (5, 0))
        self.assertEqual(len(books.ledger), 8)

    def test_each_summary_word_at_the_start_of_any_cell_and_the_vendor_subtotal_anywhere(self):
        folder = folder_with(self)
        extra = []
        for i, text in enumerate(("합계", "소계 1건", "일계", "월계(10월)", "누계: 3", "총 거래처별 소계 9건")):
            row = [""] * 10
            row[9 - i % 3] = text  # 마지막 칸들 어디든
            extra.append(row)
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER] + FAKE_JOURNAL + extra)
        entry = load(folder).files["분개장"]
        self.assertEqual((entry["skipped"], entry["undated"], entry["rows"]), (6, 0, 34))

    def test_a_dated_row_with_a_summary_cell_is_skipped_and_does_not_move_last_date(self):
        folder = folder_with(self)
        row = list(FAKE_JOURNAL[0])
        row[0], row[9] = serial(dt.date(2027, 1, 5)), "소계"
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER] + FAKE_JOURNAL + [row])
        entry = load(folder).files["분개장"]
        self.assertEqual((entry["skipped"], entry["rows"]), (1, 34))
        self.assertEqual(entry["last_date"], dt.date(2026, 10, 30))

    def test_a_word_in_the_middle_of_a_normal_cell_is_not_a_summary(self):
        folder = folder_with(self)
        row = list(FAKE_JOURNAL[0])
        row[9] = "[26201] 정산 합계 확인"
        write_xlsx(kind_path(folder, "분개장"), [JOURNAL_HEADER] + FAKE_JOURNAL + [row])
        entry = load(folder).files["분개장"]
        self.assertEqual((entry["skipped"], entry["rows"]), (0, 35))


class TestWehagoAfterRef(unittest.TestCase):
    LATE = (dt.date(2026, 11, 5), dt.date(2026, 12, 31))

    def _late_rows(self):
        return [_jl(d, 90 + i, "81900", "임차료", 1000, None, "가상임대", "미래 전표") for i, d in enumerate(self.LATE)]

    def test_rows_after_the_file_date_are_kept_and_counted(self):
        folder = folder_with(self, journal=FAKE_JOURNAL + self._late_rows())
        books = load(folder)
        entry = books.files["분개장"]
        self.assertEqual(books.state, "ok")
        self.assertEqual(entry["after_ref"], 2)
        self.assertEqual(entry["rows"], 36)
        self.assertEqual(len(books.journal), 36)
        self.assertEqual(entry["last_date"], dt.date(2026, 12, 31))
        self.assertEqual(entry["ref_date"], dt.date(2026, 10, 31))
        self.assertEqual(books.book_date, dt.date(2026, 10, 31))  # last_date 가 장부 기준일을 옮기지 않는다
        self.assertEqual(books.files["매입매출장"]["after_ref"], 0)
        self.assertEqual(books.after_ref, 2)

    def test_read_book_reports_after_ref_and_a_row_on_the_ref_date_is_not_after(self):
        folder = folder_with(self, journal=FAKE_JOURNAL + self._late_rows())
        _, info = read_kind(folder, "분개장", file_date=dt.date(2026, 10, 31))
        self.assertEqual(info["after_ref"], 2)
        _, info = read_kind(folder, "분개장", file_date=dt.date(2026, 11, 5))
        self.assertEqual(info["after_ref"], 1)  # 11-05 당일은 이후가 아니다
        _, info = read_kind(folder, "분개장")
        self.assertEqual(info["after_ref"], 0)  # 파일 날짜가 없으면 마지막 전표일이 기준일이라 이후는 없다

    def test_no_file_date_means_no_after_ref_rows(self):
        folder = folder_with(self, journal=FAKE_JOURNAL + self._late_rows())
        os.rename(kind_path(folder, "분개장"), os.path.join(folder, "분개장.xlsx"))
        books = load(folder, asof=dt.date(2026, 12, 31), stale=100)
        self.assertEqual(books.files["분개장"]["after_ref"], 0)

    def test_payment_after_the_book_date_is_not_an_already_paid_line(self):
        w = mod("wehago")
        books = with_journal(self, stamp="20261029")  # 지급 전표(5109)는 10-30: 장부 기준일 이후
        self.assertEqual(books.state, "ok")
        self.assertEqual(books.files["분개장"]["after_ref"], 2)
        m = w.match_requests(books, requests_all())
        self.assertNotEqual(m["rows"]["5109"]["status"], "이미 지급")
        self.assertEqual(label(m, "5109"), "계산서 있음")
        self.assertEqual(m["summary"]["이미 지급"]["count"], 0)

    def test_payment_on_the_book_date_still_counts(self):
        w = mod("wehago")
        books = with_journal(self, stamp="20261030")
        m = w.match_requests(books, requests_all())
        self.assertEqual(label(m, "5109"), "이미 지급 (분개장 2026-10-30 전표 20)")

    def test_a_late_second_payment_line_does_not_make_the_payment_doubtful(self):
        w = mod("wehago")
        late = pay_line(no=26, date=dt.date(2026, 11, 20))
        books = with_journal(self, extra=[late])
        self.assertEqual(books.files["분개장"]["after_ref"], 1)
        m = w.match_requests(books, requests_all())
        self.assertEqual(label(m, "5109"), "이미 지급 (분개장 2026-10-30 전표 20)")
