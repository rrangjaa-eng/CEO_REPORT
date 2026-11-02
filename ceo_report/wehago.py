"""WEHAGO 장부 엑셀(분개장·매입매출장·전자세금계산서(매입))을 표준 라이브러리로 읽고 인트라넷 요청과 대조한다. 실제 파일은 git 제외 폴더에만 둔다."""
import datetime as dt
import decimal
import os
import posixpath
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

from .approval import parse_registered, project_code  # noqa: F401  (parse_registered: 지급 확인 단계에서 쓴다)
from .util import is_blank, won
from .util import date as parse_date

# 종류 → 예상 머리글 (공백을 모두 없앤 이름). 분개장의 'Code'는 두 번 나온다 (계정 Code, 거래처 Code).
KIND_HEADERS = {
    "분개장": ("전표일자", "전표번호", "구분", "Code", "계정과목", "차변", "대변", "거래처", "Code", "적요"),
    "매입매출장": ("구분", "전표일자", "번호", "거래처", "사업자(주민)번호", "품명", "공급가액", "부가세", "합계", "신고월",
               "전자세금", "11일이내", "매입/매출유형", "분개유형"),
    "전자세금계산서(매입)": ("일자", "Code", "거래처", "유형", "품명", "공급가액", "부가세", "합계", "차변계정", "대변계정",
                    "관리", "전표상태"),
}
KINDS = tuple(KIND_HEADERS)
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_EPOCH_1900 = dt.date(1899, 12, 30)
_EPOCH_1904 = dt.date(1904, 1, 1)


class WehagoError(Exception):
    """엑셀을 읽을 수 없거나 머리글이 예상과 다를 때."""


class Rows(list):
    """read_xlsx 결과: 행 목록 + 날짜 체계(date1904)."""
    date1904 = False


# ───────────── 글자·숫자·날짜 해석 ─────────────
def mask_rrn(text):
    return text


def norm_vendor(name):
    """거래처 이름 정규화 (W-5): NFKC('㈜'→'(주)'), 공백 제거, '(주)'·'주식회사' 제거."""
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name or ""))
    return s.replace("(주)", "").replace("주식회사", "")


def _amount(text):
    """엑셀 칸 글자 → 정수 금액. 빈칸·정수가 아닌 값은 None (0이 아니다)."""
    if is_blank(text):
        return None
    s = str(text).strip().replace(",", "").replace("원", "")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        d = decimal.Decimal(s)
    except decimal.InvalidOperation:
        return None
    if not d.is_finite() or abs(d.adjusted()) > 18 or d != d.to_integral_value():
        return None
    v = int(d)
    return -v if neg else v


def _parse_date(text, date1904=False, year_ref=None):
    """엑셀 일련번호(소수부는 버림)·'YYYY-MM-DD' 계열·'YYYYMMDD'·'MM-DD'(year_ref 기준 해, W-12) → date."""
    s = (text or "").strip()
    if not s:
        return None
    if re.match(r"^\d+(\.\d+)?$", s) and len(s.split(".")[0]) != 8:
        n = int(s.split(".")[0])
        if 1 <= n <= 2958465:
            return (_EPOCH_1904 if date1904 else _EPOCH_1900) + dt.timedelta(days=n)
        return None
    m = re.match(r"^(\d{1,2})-(\d{1,2})$", s)
    if m:
        if year_ref is None:
            return None
        mm, dd = int(m.group(1)), int(m.group(2))
        year = year_ref.year - (1 if (mm, dd) > (year_ref.month, year_ref.day) else 0)
        try:
            return dt.date(year, mm, dd)
        except ValueError:
            return None
    return parse_date(s.replace("T", " "))


# ───────────── 엑셀 읽기 ─────────────
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _si_text(si):
    parts = []
    for ch in si:
        if _local(ch.tag) == "t":
            parts.append(ch.text or "")
        elif _local(ch.tag) == "r":
            parts.extend(t.text or "" for t in ch if _local(t.tag) == "t")
    return "".join(parts)


def _col_index(ref):
    letters = re.match(r"^([A-Za-z]+)", ref or "")
    if not letters:
        return None
    n = 0
    for c in letters.group(1).upper():
        n = n * 26 + ord(c) - 64
    return n - 1


def read_xlsx(path):
    """첫 시트(workbook.xml 순서, rels 로 부품 찾기)의 행 목록. 칸은 글자, 빈 칸은 ''."""
    zf = zipfile.ZipFile(path)
    try:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        date1904, rid = False, None
        for el in wb.iter():
            name = _local(el.tag)
            if name == "workbookPr":
                date1904 = el.get("date1904") in ("1", "true")
            elif name == "sheet" and rid is None:
                rid = el.get(_NS_REL + "id")
        target = None
        for el in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")):
            if el.get("Id") == rid:
                target = el.get("Target")
        if not target:
            raise WehagoError("엑셀 내부 형식이 예상과 다름")
        part = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            shared = [_si_text(si) for si in ET.fromstring(zf.read("xl/sharedStrings.xml")) if _local(si.tag) == "si"]
        root = ET.fromstring(zf.read(part))
    finally:
        zf.close()
    rows = Rows()
    rows.date1904 = date1904
    for row in root.iter():
        if _local(row.tag) != "row":
            continue
        cells = {}
        for c in row:
            if _local(c.tag) != "c":
                continue
            col = _col_index(c.get("r"))
            v = None
            for ch in c:
                if _local(ch.tag) == "v":
                    v = (ch.text or "").strip()
            if c.get("t") == "s":
                v = shared[int(v)] if v else ""
            cells[col] = v or ""
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    width = max((len(r) for r in rows), default=0)
    for r in rows:
        r.extend([""] * (width - len(r)))
    return rows


# ───────────── 장부 읽기 ─────────────
class Books:
    """load_books 결과."""

    def __init__(self):
        self.state = "자료 없음"
        self.reason = ""
        self.book_date = None
        self.files = {}
        self.header = None
        self.unused = []
        self.journal = []
        self.ledger = []
        self.einvoice = []


def _column_map(rows, kind, name):
    expected = KIND_HEADERS[kind]
    header = [re.sub(r"\s+", "", h) for h in (rows[0] if rows else [])]
    missing = [h for h in expected if h not in header]
    extra = [h for h in header if h and h not in expected]
    if missing or extra:
        raise WehagoError("%s 머리글이 예상과 다름 — 없음: %s · 추가: %s" % (name, ", ".join(missing), ", ".join(extra)))
    cols = {}
    for i, h in enumerate(header):
        cols.setdefault(h, []).append(i)
    return cols


def read_book(path, kind, file_date=None, asof=None):
    """한 파일을 머리글 이름으로 읽어 행 dict 목록과 요약을 돌려준다."""
    name = os.path.basename(path)
    rows = read_xlsx(path)
    cols = _column_map(rows, kind, name)
    year_ref = file_date or asof
    d1904 = rows.date1904

    def cell(row, header, n=0):
        return row[cols[header][n]].strip()

    out, last = [], None
    for row in rows[1:]:
        if kind == "분개장":
            date = _parse_date(cell(row, "전표일자"), d1904)
            item = {"date": date, "no": cell(row, "전표번호"), "account_code": cell(row, "Code", 0),
                    "account": cell(row, "계정과목"), "debit": _amount(cell(row, "차변")),
                    "credit": _amount(cell(row, "대변")), "vendor": mask_rrn(cell(row, "거래처")),
                    "memo": mask_rrn(cell(row, "적요"))}
            item["vendor_norm"] = norm_vendor(item["vendor"])
            item["code"] = project_code(item["memo"])
        elif kind == "매입매출장":
            date = _parse_date(cell(row, "전표일자"), d1904)
            if cell(row, "구분") != "매입":
                if date and (last is None or date > last):
                    last = date
                continue
            item = {"date": date, "no": cell(row, "번호"), "vendor": mask_rrn(cell(row, "거래처")),
                    "item": mask_rrn(cell(row, "품명")), "supply": _amount(cell(row, "공급가액")),
                    "vat": _amount(cell(row, "부가세")), "total": _amount(cell(row, "합계"))}
            item["vendor_norm"] = norm_vendor(item["vendor"])
            item["code"] = project_code(item["item"])
        else:
            date = _parse_date(cell(row, "일자"), d1904, year_ref)
            item = {"date": date, "vendor": mask_rrn(cell(row, "거래처")), "item": mask_rrn(cell(row, "품명")),
                    "supply": _amount(cell(row, "공급가액")), "vat": _amount(cell(row, "부가세")),
                    "total": _amount(cell(row, "합계")), "debit_account": mask_rrn(cell(row, "차변계정")),
                    "slip_state": cell(row, "전표상태")}
            item["vendor_norm"] = norm_vendor(item["vendor"])
            item["code"] = project_code(item["item"])
        if date and (last is None or date > last):
            last = date
        out.append(item)
    return out, {"last_date": last, "rows": len(rows) - 1}


def _file_date(name):
    for m in re.finditer(r"_(\d+)", name):
        if len(m.group(1)) == 8:
            try:
                return dt.date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:]))
            except ValueError:
                continue
    return None


def load_books(folder, asof, stale_days):
    """폴더의 세 파일을 읽어 Books 를 만든다."""
    books = Books()
    names = sorted(os.listdir(folder))
    ref_dates = []
    for kind in KINDS:
        word = kind.split("(")[0]
        found = [n for n in names if n.endswith(".xlsx") and word in n]
        if not found:
            continue
        name = found[0]
        fdate = _file_date(name)
        rows, info = read_book(os.path.join(folder, name), kind, fdate, asof)
        books.files[kind] = {"name": name, "file_date": fdate, "last_date": info["last_date"],
                             "ref_date": fdate or info["last_date"], "rows": info["rows"]}
        ref_dates.append(books.files[kind]["ref_date"])
        setattr(books, {"분개장": "journal", "매입매출장": "ledger", "전자세금계산서(매입)": "einvoice"}[kind], rows)
    if len(books.files) == len(KINDS):
        books.state = "ok"
        books.book_date = min(ref_dates)
    return books


# ───────────── 요청 대조 ─────────────
def _signed(v):
    return ("+" if v > 0 else "") + won(v)


def _invoices(books, rq):
    """같은 거래처·같은 코드의 매입 계산서: 매입매출장이 우선, 없을 때만 전자세금계산서(매입)."""
    key = norm_vendor(rq["vendor"])
    for source, rows in (("매입매출장", books.ledger), ("전자세금계산서(매입)", books.einvoice)):
        found = [r for r in rows if r["vendor_norm"] == key and r["code"] == rq["code"]]
        if found:
            return source, found
    return None, []


def match_requests(books, requests):
    rows = {}
    known = set(r["vendor_norm"] for src in (books.journal, books.ledger, books.einvoice) for r in src)
    for rq in requests:
        row = {"status": "", "label": "", "invoice_total": None, "diff": None, "schedule_amount": rq["amount"],
               "candidates": 0, "source": None, "payment": None}
        rows[rq["번호"]] = row
        if rq["amount"] is None:
            row["status"], row["label"] = "연결 불가", "연결 불가 (금액 미확인)"
        elif norm_vendor(rq["vendor"]) not in known:
            row["status"], row["label"] = "연결 불가", "연결 불가 (거래처 후보 0건)"
        elif not rq["code"]:
            row["status"], row["label"] = "연결 불가", "연결 불가 (프로젝트 코드 없음)"
        else:
            source, found = _invoices(books, rq)
            suffix = "" if source == "매입매출장" else " (전자세금계산서)"
            exact = [r for r in found if r["total"] == rq["amount"]]
            row["source"], row["candidates"] = source, len(found)
            if not found:
                row["status"], row["label"] = "계산서 없음", "계산서 없음"
            elif len(exact) == 1:
                row["status"], row["label"] = "계산서 있음", "계산서 있음" + suffix
                row["invoice_total"], row["diff"] = exact[0]["total"], 0
            elif not exact and len(found) == 1 and found[0]["total"] is not None:
                total = found[0]["total"]
                row["status"] = "금액 차이"
                row["invoice_total"], row["diff"] = total, total - rq["amount"]
                row["label"] = "금액 차이 (계산서 %s · 차액 %s)%s" % (won(total), _signed(row["diff"]), suffix)
                row["schedule_amount"] = total
            else:
                row["status"], row["label"] = "연결 불가", "연결 불가 (계산서 후보 %d건)" % len(found)
    return {"rows": rows, "summary": {}}
