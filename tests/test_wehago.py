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
import unittest
import zipfile
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


if __name__ == "__main__":
    unittest.main()
