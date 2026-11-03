"""WEHAGO 장부 엑셀(분개장·매입매출장·전자세금계산서(매입))을 표준 라이브러리로 읽고 인트라넷 요청과 대조한다. 실제 파일은 git 제외 폴더에만 둔다."""
import datetime as dt
import decimal
import os
import posixpath
import re
import unicodedata
import zipfile
import zlib
from collections import OrderedDict
import xml.etree.ElementTree as ET

from .approval import parse_registered, project_code  # noqa: F401  (parse_registered: 지급 확인 단계에서 쓴다)
from .util import is_blank, mask_rrn, ssum_or_none, won
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
# 매출 계산서 원천 (D-41): 고른 매입매출장의 매출 줄이 없을 때 쓰는 별도 파일 두 가지. 매입 쪽 장부로는 고르지 않는다.
SALES_KINDS = ("매입매출장(매출)", "전자세금계산서(매출)")
MAX_PART_BYTES = 50 * 1024 * 1024  # 엑셀 안 부품 하나의 풀린 크기 상한 (T-01.1-41)
MAX_COLS = 256
_BAD = "엑셀 내부 형식이 예상과 다름"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_EPOCH_1900 = dt.date(1899, 12, 30)
_EPOCH_1904 = dt.date(1904, 1, 1)


class WehagoError(Exception):
    """엑셀을 읽을 수 없거나 머리글이 예상과 다를 때."""


class HeaderMismatch(WehagoError):
    """필수 열이 없거나 이름이 다름: 없음 이름과, 함께 있던 추가 이름을 가진다 (D-35a, D-35c: 추가 열만으로는 멈추지 않는다)."""

    def __init__(self, file, kind, missing, extra):
        parts = (["없음: " + ", ".join(missing)] if missing else []) + (["추가: " + ", ".join(extra)] if extra else [])
        WehagoError.__init__(self, "%s 머리글이 예상과 다름 — %s" % (file, " · ".join(parts)))
        self.file, self.kind, self.missing, self.extra = file, kind, missing, extra


class Rows(list):
    """read_xlsx 결과: 행 목록 + 날짜 체계(date1904)."""
    date1904 = False


# ───────────── 글자·숫자·날짜 해석 ─────────────
def norm_vendor(name):
    """거래처 이름 정규화 (W-5): NFKC('㈜'→'(주)'), 공백 제거, '(주)'·'주식회사' 제거."""
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name or ""))
    return s.replace("(주)", "").replace("주식회사", "")


def _amount(text):
    """엑셀 칸 글자 → 정수 금액. 빈칸·오류·정수가 아닌 값은 None (0이 아니다)."""
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
    """공유 문자열 한 개: t 글자, 또는 r/t 조각 이어 붙임 (발음 표기 rPh 는 뺀다)."""
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


def _part(zf, name):
    """부품 한 개의 바이트. 크기 상한과 DOCTYPE/ENTITY 검사를 파싱 전에 한다. 디스크에 풀지 않는다 (T-01.1-41)."""
    try:
        info = zf.getinfo(name)
    except KeyError:
        raise WehagoError(_BAD)
    if info.file_size > MAX_PART_BYTES:
        raise WehagoError("엑셀 파일이 너무 큼")
    with zf.open(info) as f:
        data = f.read(MAX_PART_BYTES + 1)
    if len(data) > MAX_PART_BYTES:
        raise WehagoError("엑셀 파일이 너무 큼")
    up = data.upper()
    for enc in ("utf-8", "utf-16-le", "utf-16-be"):
        for tag in ("<!DOCTYPE", "<!ENTITY"):
            if tag.encode(enc) in up:
                raise WehagoError(_BAD)
    return data


def _sheet_rows(zf):
    wb = ET.fromstring(_part(zf, "xl/workbook.xml"))
    date1904, rid = False, None
    for el in wb.iter():
        name = _local(el.tag)
        if name == "workbookPr":
            date1904 = el.get("date1904") in ("1", "true")
        elif name == "sheet" and rid is None:
            rid = el.get(_NS_REL + "id")
    target = None
    for el in ET.fromstring(_part(zf, "xl/_rels/workbook.xml.rels")):
        if rid is not None and el.get("Id") == rid:
            target = el.get("Target")
    if not target:
        raise WehagoError(_BAD)
    sheet_part = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
    shared = []
    if "xl/sharedStrings.xml" in zf.namelist():
        shared = [_si_text(si) for si in ET.fromstring(_part(zf, "xl/sharedStrings.xml")) if _local(si.tag) == "si"]
    root = ET.fromstring(_part(zf, sheet_part))
    rows = Rows()
    rows.date1904 = date1904
    for row in root.iter():
        if _local(row.tag) != "row":
            continue
        if not rows:  # 1행이 비어 파일에 없으면 머리글 줄은 빈 줄이다
            first = row.get("r")
            if first and first.isdigit() and int(first) != 1:
                rows.append([])
        cells, prev = {}, -1
        for c in row:
            if _local(c.tag) != "c":
                continue
            col = _col_index(c.get("r"))
            col = prev + 1 if col is None else col  # r 이 없는 칸은 앞 칸 다음 열 (W-14)
            prev = col
            if col >= MAX_COLS:
                raise WehagoError(_BAD)
            kind, v, inline = c.get("t"), "", None
            for ch in c:
                if _local(ch.tag) == "v":
                    v = (ch.text or "").strip()
                elif _local(ch.tag) == "is":
                    inline = _si_text(ch)
            if kind == "s":
                v = shared[int(v)]
            elif kind == "inlineStr":
                v = inline or ""
            elif kind in ("e", "b"):
                v = ""  # 오류·참거짓 칸은 값이 없는 칸 (0이 아니다)
            cells[col] = v
        rows.append([cells.get(i, "") for i in range(max(cells) + 1 if cells else 0)])
    width = max((len(r) for r in rows), default=0)
    for r in rows:
        r.extend([""] * (width - len(r)))
    return rows


def read_xlsx(path):
    """첫 시트(workbook.xml 순서, rels 로 부품 찾기)의 행 목록. 칸은 글자, 빈 칸은 ''. 실패는 WehagoError."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, EOFError):
        raise WehagoError("엑셀 파일을 열 수 없음")
    try:
        return _sheet_rows(zf)
    except WehagoError:
        raise
    except ET.ParseError:
        raise WehagoError(_BAD)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error, OSError):
        raise WehagoError("엑셀 파일을 열 수 없음")
    except (KeyError, ValueError, IndexError, AttributeError, TypeError, OverflowError):
        raise WehagoError(_BAD)
    finally:
        zf.close()


# ───────────── 장부 읽기 ─────────────
class Books:
    """load_books 결과."""

    def __init__(self):
        self.state = "자료 없음"
        self.reason = ""
        self.book_date = None
        self.after_ref = 0  # 장부 기준일 이후 전표 수 (파일별 값의 합, D-35c)
        self.files = {}
        self.header = None
        self.unused = []
        self.journal = []
        self.ledger = []
        self.einvoice = []
        # 매입매출장 '프로젝트명' 칸의 코드: {(전표일자 ISO, 번호 글자): 프로젝트 코드} (D-53). 칸이 없거나 비면 빈 dict
        self.slip_projects = {}
        # D-57: 분개장 매입전표·매출전표로 만든 계산서 단위 자료 (인쇄 분개장에 '유형' 칸이 있을 때). sales 는 load_sales 가 쓴다
        self.from_journal = False
        self.journal_sales = []
        self.notes = []   # 변환결과.txt 에 쓰는 장부 알림 (매입매출장 대조 등)


_SUBTOTAL = ("일계", "월계", "누계", "합계", "소계")


def _check_header(rows, kind, name):
    """필수 열 이름(공백 제거)이 모두 있어야 한다. 같은 이름은 나타난 순서로 짝짓는다 (W-2).

    필수 열이 없거나 이름이 다르면 HeaderMismatch. 추가 열은 무시하고 (D-35c) (열 위치, 추가 열 이름 목록)을 돌려준다.
    """
    header = [re.sub(r"\s+", "", h) for h in (rows[0] if rows else [])]
    while header and not header[-1]:
        header.pop()
    remaining = list(header)
    missing = []
    for h in KIND_HEADERS[kind]:
        if h in remaining:
            remaining.remove(h)
        else:
            missing.append(h)
    extra = [h or "(빈칸)" for h in remaining]
    if missing:
        raise HeaderMismatch(name, kind, missing, extra)
    cols = {}
    for i, h in enumerate(header):
        cols.setdefault(h, []).append(i)
    return cols, extra


def _is_subtotal(row):
    """합계·소계·일계·월계·누계로 시작하거나 '거래처별 소계'를 포함한 칸이 하나라도 있는가 (D-35c).

    요약 줄 판정은 read_book 이 이 검사와 '날짜 칸이 날짜로 읽히지 않음'을 함께 본다 (WR-02, D-35d).
    """
    for c in row:
        s = re.sub(r"\s+", "", c)  # 실제 파일은 '합       계'처럼 글자 사이에 공백을 넣는다
        if "거래처별소계" in s:
            return True
        s = s.lstrip("[]()<>【】「」")
        if s.startswith(_SUBTOTAL) or s.startswith(("분기누계", "반기누계")):
            return True
    return False


_PRINT_JOURNAL = {"일자": "전표일자", "전표번호": "전표번호", "계정코드": "Code", "계정과목": "계정과목", "적요": "적요",
                  "차변": "차변", "대변": "대변", "거래처코드": "거래처Code", "거래처명": "거래처"}


def _xls_text(v):
    if isinstance(v, float):
        return "%d" % v if v == int(v) else repr(v)
    return v


def read_journal_xls(path):
    """분개장 인쇄 저장 파일(.xls, D-56) -> read_xlsx 와 같은 모양(첫 줄 KIND_HEADERS['분개장'] 머리글, 전표 줄만).

    '기 간 : YYYY년 MM월 DD일 ~' 의 시작일로 'MM/DD' 일자에 해를 붙인다 (시작 월일보다 앞선 월일은 다음 해).
    쪽마다 되풀이되는 회사명·머리글 줄, 빈 줄, '합 계' 줄은 뺀다. 구분 칸은 인쇄 파일의 '유형'(일반전표·매입전표…)이다.
    """
    from .xls import XlsError, read_xls
    name = os.path.basename(path)
    try:
        grid = read_xls(path)
    except XlsError as e:
        raise WehagoError(str(e))
    start, hdr = None, None
    for i, row in enumerate(grid[:40]):
        cells = [c for c in row if isinstance(c, str)]
        for c in cells:
            m = re.search(r"기\s*간\s*:\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", c)
            if m and start is None:
                start = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if row and isinstance(row[0], str) and re.sub(r"\s+", "", row[0]) == "일자":
            hdr = i
            break
    if hdr is None or start is None:
        raise WehagoError("분개장 인쇄 파일 모양이 아님 (기간·머리글을 찾지 못함)")
    names = [re.sub(r"\s+", "", c) if isinstance(c, str) else "" for c in grid[hdr]]
    missing = [h for h in _PRINT_JOURNAL if h not in names]
    if missing:
        raise HeaderMismatch(name, "분개장", missing, [])
    col = dict((h, names.index(h)) for h in _PRINT_JOURNAL)
    sort_col = names.index("유형") if "유형" in names else None
    proj_col = names.index("프로젝트명") if "프로젝트명" in names else None
    out = Rows([["전표일자", "전표번호", "구분", "Code", "계정과목", "차변", "대변", "거래처", "Code", "적요"]
                + (["프로젝트명"] if proj_col is not None else [])])
    out.known_extra = ("프로젝트명",)
    for row in grid[hdr + 1:]:
        row = list(row) + [""] * (len(names) - len(row))
        a = row[col["일자"]]
        m = re.match(r"^\s*(\d{1,2})/(\d{1,2})\s*$", a) if isinstance(a, str) else None
        if not m:
            continue   # 쪽 머리(회사명·머리글), 빈 줄, '합 계'
        mm, dd = int(m.group(1)), int(m.group(2))
        year = start.year + (1 if (mm, dd) < (start.month, start.day) else 0)
        try:
            day = dt.date(year, mm, dd).isoformat()
        except ValueError:
            day = a
        g = lambda h: _xls_text(row[col[h]])
        out.append([day, g("전표번호"), _xls_text(row[sort_col]) if sort_col is not None else "", g("계정코드"),
                    g("계정과목"), g("차변"), g("대변"), g("거래처명"), g("거래처코드"), g("적요")]
                   + ([_xls_text(row[proj_col])] if proj_col is not None else []))
    return out


def read_book(path, kind, file_date=None, asof=None, keep_sales=False):
    """한 파일을 머리글 이름으로 읽어 (행 dict 목록, 요약)을 돌려준다. 머리글이 다르면 HeaderMismatch.

    keep_sales 가 참이면 매입매출장의 매출 줄을 info["sales_rows"] 에 남긴다 (매입 줄과 같은 열 + type = 매입/매출유형 글자).
    기본값에서는 info["sales_rows"] 는 빈 목록이고 행 목록과 다른 요약 값은 이전과 같다.
    """
    name = os.path.basename(path)
    rows = read_journal_xls(path) if kind == "분개장" and path.lower().endswith(".xls") else read_xlsx(path)
    cols, extra = _check_header(rows, kind, name)
    extra = [h for h in extra if h not in getattr(rows, "known_extra", ())]
    year_ref = (file_date or asof) if kind == "전자세금계산서(매입)" else None  # 'MM-DD'는 전자세금계산서만 (W-12)
    d1904 = rows.date1904
    date_col = {"분개장": "전표일자", "매입매출장": "전표일자", "전자세금계산서(매입)": "일자"}[kind]

    def txt(row, header, n=0):
        return mask_rrn(row[cols[header][n]].strip())

    out, last = [], None
    info = {"last_date": None, "rows": 0, "skipped": 0, "undated": 0, "sales": 0, "other": 0, "after_ref": 0,
            "extra_columns": list(extra), "extra_note": ("추가 열 무시: " + ", ".join(extra)) if extra else "",
            "sales_rows": [], "slip_projects": {}}
    slips = {}   # (전표일자 ISO, 번호) -> 코드, 한 전표에 서로 다른 코드가 있으면 None (쓰지 않음)
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            info["skipped"] += 1
            continue
        date = _parse_date(row[cols[date_col][0]], d1904, year_ref)
        if date is None and _is_subtotal(row):
            # 합계·소계·일계·월계·누계 줄: 저장하지 않고 마지막 날짜·날짜 없음에도 넣지 않는다 (W-14, D-35c).
            # 날짜가 읽히는 줄은 적요·거래처·품명이 '합계…'로 시작해도 실제 전표다 (WR-02, D-35d)
            info["skipped"] += 1
            continue
        info["rows"] += 1
        if date is None:
            info["undated"] += 1
        else:
            last = date if last is None or date > last else last
            if file_date is not None and date > file_date:
                info["after_ref"] += 1  # 장부 기준일(파일 이름 날짜) 이후 전표: 남기되 센다 (D-35c)
        if kind == "분개장":
            item = {"date": date, "no": txt(row, "전표번호"), "account_code": txt(row, "Code", 0),
                    "account": txt(row, "계정과목"), "debit": _amount(row[cols["차변"][0]]),
                    "credit": _amount(row[cols["대변"][0]]), "vendor": txt(row, "거래처"), "memo": txt(row, "적요"),
                    "sort": txt(row, "구분")}
            item["code"] = project_code(item["memo"])
            if "프로젝트명" in cols:   # 인쇄 분개장의 프로젝트 칸 (D-57): 전표별 코드는 D-53 과 같은 규칙
                item["project_name"] = txt(row, "프로젝트명")
                pcode = project_code(item["project_name"])
                if pcode and date is not None:
                    k = (date.isoformat(), item["no"])
                    slips[k] = pcode if slips.get(k, pcode) == pcode else None
        elif kind == "매입매출장":
            sort = row[cols["구분"][0]].strip()
            if "프로젝트명" in cols and date is not None:   # 추가 열 (D-53): 매입·매출 줄 모두 전표별 코드로 남긴다
                pcode = project_code(txt(row, "프로젝트명"))
                if pcode:
                    k = (date.isoformat(), row[cols["번호"][0]].strip())
                    slips[k] = pcode if slips.get(k, pcode) == pcode else None
            if sort != "매입":  # 매출 줄은 세고 (keep_sales 일 때만 남긴다). 사업자(주민)번호 칸은 아예 읽지 않는다 (W-11)
                info["sales" if sort == "매출" else "other"] += 1
                if sort != "매출" or not keep_sales:
                    continue
            item = {"date": date, "no": txt(row, "번호"), "vendor": txt(row, "거래처"), "item": txt(row, "품명"),
                    "supply": _amount(row[cols["공급가액"][0]]), "vat": _amount(row[cols["부가세"][0]]),
                    "total": _amount(row[cols["합계"][0]])}
            item["code"] = project_code(item["item"])
            if sort == "매출":
                item["type"] = txt(row, "매입/매출유형")
                item["vendor_norm"] = norm_vendor(item["vendor"])
                info["sales_rows"].append(item)
                continue
        else:
            item = {"date": date, "vendor": txt(row, "거래처"), "item": txt(row, "품명"),
                    "supply": _amount(row[cols["공급가액"][0]]), "vat": _amount(row[cols["부가세"][0]]),
                    "total": _amount(row[cols["합계"][0]]), "debit_account": txt(row, "차변계정"),
                    "slip_state": txt(row, "전표상태"), "credit_account": txt(row, "대변계정"), "type": txt(row, "유형")}
            item["code"] = project_code(item["item"])
        item["vendor_norm"] = norm_vendor(item["vendor"])
        out.append(item)
    info["last_date"] = last
    info["slip_projects"] = dict((k, v) for k, v in slips.items() if v)
    return out, info


def _file_date(name):
    """파일 이름에서 '_' 뒤 첫 8자리 숫자(YYYYMMDD). 없으면 이름 앞 'YYMMDD '(인쇄 저장 파일, 예: '261103 분개장.xls')."""
    for m in re.finditer(r"_(\d+)", name):
        if len(m.group(1)) == 8:
            try:
                return dt.date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:]))
            except ValueError:
                continue
    m = re.match(r"^(\d{2})(\d{2})(\d{2})\s", os.path.basename(name))
    if m:
        try:
            return dt.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _rank_date(name):
    """파일 고르기용 날짜. 이름에 내려받은 날보다 앞선 해(예: '261103 분개장_2025.xls')가 따로 있으면 그 해의 12월 31일로 본다
    (작년 기수 파일을 올해 파일보다 새것으로 고르지 않는다, 2026-11-03 실제 파일)."""
    fd = _file_date(name)
    if fd is None:
        return None
    base = re.sub(r"^\d{6}\s", "", os.path.basename(name))
    years = [int(y) for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", base) if int(y) < fd.year]
    return dt.date(max(years), 12, 31) if years else fd


def _sales_kind_of(name):
    """매출 계산서 원천 파일 이름의 종류 (SALES_KINDS 중 하나) 또는 None. '매입매출장' 글자를 빼고도 '매출'이 남아야 한다."""
    if "매입매출장" in name and "매출" in name.replace("매입매출장", ""):
        return "매입매출장(매출)"
    if "전자세금계산서" in name and "매출" in name:
        return "전자세금계산서(매출)"
    return None


def _kind_of(name):
    """파일 이름이 속하는 종류와 읽어도 되는지. 매출 전자세금계산서·매입매출장(매출)은 종류는 같지만 매입 쪽으로는 읽지 않는다 (W-1)."""
    if "매입매출장" in name:
        return "매입매출장", _sales_kind_of(name) is None
    if "분개장" in name:
        return "분개장", True
    if "전자세금계산서" in name:
        return "전자세금계산서(매입)", "매출" not in name
    return None, False


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


# ───────────── 분개장 매입·매출 전표 -> 계산서 단위 (D-57) ─────────────
INVOICE_SORTS = {"매입전표": "매입", "매출전표": "매출"}
VAT_IN_CODES = ("13500",)    # 부가세대급금
VAT_OUT_CODES = ("25500",)   # 부가세예수금


def invoices_from_journal(journal):
    """분개장 '유형'이 매입전표·매출전표인 전표를 (전표일자, 전표번호)로 묶어 계산서 한 장씩 -> (매입 행, 매출 행).

    매입: 합계 = 차변 합(공제받지 못한 부가세는 비용 쪽에 들어 있어 실제 지급액과 같다), 부가세 = 부가세대급금 차변,
    공급가액 = 합계 − 부가세, 거래처 = 대변 줄 거래처. 매출: 합계 = 대변 합, 부가세 = 부가세예수금 대변, 거래처 = 차변 줄 거래처.
    품명은 첫 비용·매출 줄 적요, 코드는 프로젝트 칸 → 적요 [코드] 순. 매입매출장(매입·매출) 행과 같은 열을 쓴다.
    """
    groups = OrderedDict()
    for line in journal:
        kind = INVOICE_SORTS.get((line.get("sort") or "").strip())
        if kind is None or line["date"] is None:
            continue
        groups.setdefault((kind, line["date"], line["no"]), []).append(line)
    buys, sales = [], []
    for (kind, date, no), lines in groups.items():
        side, other = ("debit", "credit") if kind == "매입" else ("credit", "debit")
        vat_codes = VAT_IN_CODES if kind == "매입" else VAT_OUT_CODES
        total = sum(ln[side] or 0 for ln in lines)
        vat = sum(ln[side] or 0 for ln in lines if _squash(ln["account_code"]) in vat_codes)
        main = [ln for ln in lines if ln[side] and _squash(ln["account_code"]) not in vat_codes]
        party = [ln for ln in lines if ln[other] and ln["vendor"]]
        vendor = (party or [ln for ln in lines if ln["vendor"]] or [{"vendor": ""}])[0]["vendor"]
        item = main[0]["memo"] if main else (lines[0]["memo"] or "")
        code = next((project_code(ln.get("project_name", "")) for ln in lines if project_code(ln.get("project_name", ""))),
                    None) or project_code(item)
        row = {"date": date, "no": no, "vendor": vendor, "item": item, "supply": total - vat, "vat": vat, "total": total,
               "code": code, "vendor_norm": norm_vendor(vendor)}
        if kind == "매출":
            row["type"] = ""
            sales.append(row)
        else:
            buys.append(row)
    return buys, sales


def compare_invoices(derived, ledger_rows, label):
    """분개장으로 만든 계산서와 매입매출장 행을 (전표일자, 번호)별 합계로 대조 -> 알림 줄 목록 (차이는 앞 10건)."""
    def by_key(rows):
        out = OrderedDict()
        for r in rows:
            k = (r["date"], str(r.get("no", "")).lstrip("0"))
            out[k] = out.get(k, 0) + (r["total"] or 0)
        return out
    a, b = by_key(derived), by_key(ledger_rows)
    diffs = [(k, b.get(k), a.get(k)) for k in sorted(set(a) | set(b), key=lambda x: (x[0] or dt.date.min, x[1]))
             if a.get(k) != b.get(k)]
    head = "매입매출장 대조(%s): 분개장 %d건 · 매입매출장 %d건 · 같음 %d건 · 다름 %d건" % (
        label, len(a), len(b), len(set(a) & set(b)) - sum(1 for k, x, y in diffs if x is not None and y is not None),
        len(diffs))
    lines = [head]
    for (d, no), x, y in diffs[:10]:
        lines.append("  %s %s 전표 %s: 매입매출장 %s · 분개장 %s" % (label, d.isoformat() if d else "날짜 없음", no,
                                                             "없음" if x is None else won(x) + "원", "없음" if y is None else won(y) + "원"))
    if len(diffs) > 10:
        lines.append("  … 그 밖에 %d건" % (len(diffs) - 10))
    return lines


def _years(rows):
    return set(r["date"].year for r in rows if r.get("date") is not None)


def _prior_years(folder, kind, names, rows, asof):
    """지난 기수 파일 (해를 넘는 프로젝트, 2026-11-03): WEHAGO 는 기수(연도)마다 따로 내려받는다.

    names(새 것부터) 중 모든 전표일자가 이미 고른 행들의 가장 이른 연도보다 앞선 해인 파일만 앞에 붙인다. 같은 해가 섞인
    파일(같은 기수의 이전 내려받기)이나 읽을 수 없는 파일은 쓰지 않는다 -> (붙일 행, 붙인 파일 이름, 쓰지 않은 파일 이름).
    매입매출장 프로젝트명 칸(D-53)은 가장 새 파일 것만 쓴다.
    """
    years = _years(rows)
    floor = min(years) if years else None
    added, used, skipped = [], [], []
    for n in names:
        try:
            more, _ = read_book(os.path.join(folder, n), kind, _file_date(n), asof)
        except Exception:  # 지난 파일이 깨졌으면 쓰지 않을 뿐 장부 전체를 멈추지 않는다
            skipped.append(n)
            continue
        ys = _years(more)
        if floor is None or not ys or max(ys) >= floor:
            skipped.append(n)
            continue
        added = more + added
        used.append(n)
        floor = min(ys)
    return added, sorted(used), skipped


def load_books(folder, asof, stale_days):
    """폴더의 세 종류 파일을 골라 읽는다. 없음·오래됨·머리글 다름·읽기 실패는 state 로 알리고 예외를 내지 않는다 (W-1~W-4).

    stale_days 가 None 이면 오래됨(경과) 판정만 건너뛴다. 장부 기준일을 알 수 없는 장부는 그래도 '경과'다.
    """
    books = Books()
    try:
        names = sorted(os.listdir(folder))
        folder_ok = True
    except OSError:
        names, folder_ok = [], False
    candidates = dict((k, []) for k in KINDS)
    lookalikes = dict((k, []) for k in KINDS)
    unused = []
    for n in names:
        if n.startswith("~$") or not os.path.isfile(os.path.join(folder, n)):  # 엑셀이 열어 둔 파일 표시는 건너뛴다
            continue
        kind, readable = _kind_of(n)
        if kind is None:
            continue
        ext = os.path.splitext(n)[1].lower()
        if ext == ".xlsx" or (ext == ".xls" and kind == "분개장"):   # 분개장은 인쇄 저장 .xls 도 읽는다 (D-56)
            (candidates[kind] if readable else unused).append(n)
        elif readable and ext in (".xls", ".csv"):
            lookalikes[kind].append(n)
    chosen, others = {}, {}
    for kind in KINDS:
        if candidates[kind]:
            ranked = sorted(candidates[kind], key=lambda n: (_rank_date(n) or dt.date.min,
                                                             _mtime(os.path.join(folder, n)), n))
            chosen[kind] = ranked[-1]
            others[kind] = ranked[-2::-1]   # 새 것부터: 지난 기수 파일 후보

    staged, mismatches, failures, slip_projects = {}, [], [], {}
    journal_slips, ledger_sales, side = {}, [], {}   # side: 분개장 기준일 때 매입매출장·전자세금계산서 문제 (멈추지 않음)
    for kind in KINDS:
        name = chosen.get(kind)
        if name is None:
            continue
        fdate = _file_date(name)
        entry = {"name": name, "file_date": fdate, "last_date": None, "ref_date": fdate, "rows": 0, "skipped": 0,
                 "undated": 0, "after_ref": 0, "extra_columns": [], "extra_note": "", "prior": []}
        books.files[kind] = entry
        try:
            rows, info = read_book(os.path.join(folder, name), kind, fdate, asof, keep_sales=kind == "매입매출장")
        except HeaderMismatch as e:
            entry["error"] = str(e)
            mismatches.append(e)
            side[kind] = str(e)
        except WehagoError as e:
            entry["error"] = str(e)
            failures.append("%s 읽기 실패 — %s" % (name, e))
            side[kind] = failures[-1]
        except Exception:  # 깨진 파일이 어떤 모양이든 화면을 멈추지 않는다
            entry["error"] = "엑셀 내용을 읽을 수 없음"
            failures.append("%s 읽기 실패 — 엑셀 내용을 읽을 수 없음" % name)
            side[kind] = failures[-1]
        else:
            entry.update(dict((k, info[k]) for k in ("last_date", "rows", "skipped", "undated", "sales", "other",
                                                     "after_ref", "extra_columns", "extra_note")))
            entry["ref_date"] = fdate or info["last_date"]
            prior_rows, entry["prior"], skipped = _prior_years(folder, kind, others.get(kind, []), rows, asof)
            unused.extend(skipped)
            staged[kind] = prior_rows + rows
            if kind == "매입매출장":
                slip_projects = info["slip_projects"]
                ledger_sales = info["sales_rows"]
            elif kind == "분개장":
                journal_slips = info["slip_projects"]
    # D-57: 인쇄 분개장에 매입전표·매출전표가 있으면 분개장 하나로 충분하다. 매입매출장·전자세금계산서(매입)는 있으면 대조만 한다
    derived = invoices_from_journal(staged["분개장"]) if "분개장" in staged else ([], [])
    from_journal = bool(derived[0] or derived[1])
    if from_journal:
        basis = ("분개장",)
        mismatches = [e for e in mismatches if e.kind == "분개장"]
        failures = [f for f in failures if f not in [v for k, v in side.items() if k != "분개장"]]
        for k, v in side.items():
            if k != "분개장":
                books.notes.append("%s 대조 못함 — %s" % (k, v))
    else:
        basis = KINDS
    for kind in KINDS:   # 읽지 못한 종류의 다른 파일도 쓰지 않은 파일이다
        if kind not in staged:
            unused.extend(others.get(kind, []))
    books.unused = sorted(unused)
    refs = [books.files[k]["ref_date"] for k in basis if k in books.files and books.files[k]["ref_date"]]
    books.book_date = min(refs) if refs else None
    books.after_ref = sum(e["after_ref"] for e in books.files.values())

    missing = [k for k in basis if k not in chosen]
    if mismatches:
        books.state = "머리글 다름"
        books.reason = "; ".join(str(e) for e in mismatches)
        e = mismatches[0]
        books.header = {"file": e.file, "kind": e.kind, "missing": list(e.missing), "extra": list(e.extra)}
    elif failures:
        books.state, books.reason = "읽기 실패", "; ".join(failures)
    elif missing:
        books.state = "자료 없음"
        books.reason = "자료 없음: " + ", ".join(missing)
        hints = ["%s 있음" % n for k in missing for n in lookalikes[k]]
        if hints:
            books.reason += " — .xlsx만 읽음 (%s)" % ", ".join(hints)
        if not folder_ok:
            books.reason += " (폴더를 찾을 수 없음)"
    else:
        ref_all = [books.files[k]["ref_date"] for k in basis]
        if None in ref_all:
            books.state = "경과"
            books.reason = "장부 기준일을 알 수 없음 (파일 이름에 날짜가 없고 전표일자도 없음)"
        else:
            late = (asof - books.book_date).days
            if stale_days is not None and late > stale_days:  # None: 나이로는 멈추지 않는다 (변환, 02-01)
                oldest = [k for k in basis if books.files[k]["ref_date"] == books.book_date][0]
                books.state = "경과"
                books.reason = "장부 기준일 %s, 기준일보다 %d일 이전 (%s)" % (books.book_date.isoformat(), late, oldest)
            else:
                books.state = "ok"
    if books.state == "ok" and from_journal:
        books.journal, books.ledger, books.einvoice = staged["분개장"], derived[0], []
        books.journal_sales, books.from_journal = derived[1], True
        books.slip_projects = journal_slips
        books.notes.insert(0, "계산서 자료: 분개장 매입전표 %d건 · 매출전표 %d건 (분개장 기준, 매입매출장·전자세금계산서는 있으면 대조만)"
                           % (len(derived[0]), len(derived[1])))
        if "매입매출장" in staged:
            books.notes.extend(compare_invoices(derived[0], staged["매입매출장"], "매입"))
            books.notes.extend(compare_invoices(derived[1], ledger_sales, "매출"))
        if "전자세금계산서(매입)" in staged:
            books.notes.append("전자세금계산서(매입) %s 은(는) 쓰지 않음 (분개장 매입전표 기준)"
                               % books.files["전자세금계산서(매입)"]["name"])
    elif books.state == "ok":  # 부분 사용 없음: ok 일 때만 행을 준다 (D-35a)
        books.journal, books.ledger, books.einvoice = staged["분개장"], staged["매입매출장"], staged["전자세금계산서(매입)"]
        books.slip_projects = slip_projects
    return books


# ───────────── 매출 계산서 원천 (D-41) ─────────────
_SALES_NONE = "자료 없음 (매출 계산서 엑셀)"


def _sales_row(item):
    """세 원천의 행을 같은 모양으로 (원천에 없는 열은 빈 글자)."""
    return {"date": item["date"], "no": item.get("no", ""), "vendor": item["vendor"], "vendor_norm": item["vendor_norm"],
            "item": item["item"], "supply": item["supply"], "vat": item["vat"], "total": item["total"],
            "code": item["code"], "type": item.get("type", ""), "credit_account": item.get("credit_account", "")}


def load_sales(folder, asof, books):
    """매출 계산서 원천을 골라 읽는다 -> dict(state, reason, source, file, file_date, rows, notes). 예외를 내지 않는다.

    우선순위(첫 번째로 있는 것): (a) load_books 가 고른 매입매출장의 매출 줄, (b) 가장 새 '매입매출장(매출)' xlsx,
    (c) 가장 새 '전자세금계산서(매출)' xlsx. 고른 파일이 틀리면 낮은 원천으로 넘어가지 않는다 (새 계산서를 놓칠 수 있다).
    state: 'ok' | '자료 없음' | '머리글 다름' | '읽기 실패'. 매출 줄이 하나도 없는 파일은 쓰지 않는다 ('자료 없음').
    """
    res = {"state": "자료 없음", "reason": _SALES_NONE, "source": "", "file": "", "file_date": None, "rows": [],
           "notes": []}
    if books is not None and getattr(books, "from_journal", False):
        # D-57: 분개장 매출전표가 계산서 원천이다 (매출 계산서 엑셀은 받지 않는다)
        name = books.files["분개장"]["name"]
        res.update({"source": "분개장 매출전표", "file": name, "file_date": _file_date(name)})
        if not books.journal_sales:
            res["reason"] = "%s — %s에 매출전표가 없음" % (_SALES_NONE, name)
            return res
        res["rows"] = [_sales_row(r) for r in books.journal_sales]
        res["state"], res["reason"] = "ok", ""
        return res
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    found = dict((k, []) for k in SALES_KINDS)
    lookalikes = []
    for n in names:
        if n.startswith("~$") or not os.path.isfile(os.path.join(folder, n)):
            continue
        kind = _sales_kind_of(n)
        if kind is None:
            continue
        ext = os.path.splitext(n)[1].lower()
        if ext == ".xlsx":
            found[kind].append(n)
        elif ext in (".xls", ".csv"):
            lookalikes.append(n)
    ledger = books.files.get("매입매출장") if books is not None else None
    chosen = None   # (원천 이름, 파일 이름, 읽는 종류, 매출 줄 남김)
    if ledger and not ledger.get("error") and (ledger.get("sales") or 0) > 0:
        chosen = ("매입매출장", ledger["name"], "매입매출장", True)
    else:
        for source, read_kind in (("매입매출장(매출)", "매입매출장"), ("전자세금계산서(매출)", "전자세금계산서(매입)")):
            if found[source]:
                ranked = sorted(found[source], key=lambda n: (_file_date(n) or dt.date.min,
                                                              _mtime(os.path.join(folder, n)), n))
                chosen = (source, ranked[-1], read_kind, source == "매입매출장(매출)")
                break
    if chosen is None:
        if lookalikes:
            res["reason"] += " — .xlsx만 읽음 (%s)" % ", ".join("%s 있음" % n for n in lookalikes)
        return res
    source, name, read_kind, keep = chosen
    unused = sorted(n for k in SALES_KINDS for n in found[k] if n != name)
    if unused:
        res["notes"].append("쓰지 않은 매출 파일: " + ", ".join(unused))
    res["source"], res["file"], res["file_date"] = source, name, _file_date(name)
    try:
        rows, info = read_book(os.path.join(folder, name), read_kind, res["file_date"], asof, keep_sales=keep)
    except HeaderMismatch as e:
        res["state"] = "머리글 다름"
        res["reason"] = "매출 계산서 엑셀 머리글 다름 — %s: 없는 열 %s" % (name, ", ".join(e.missing))
        return res
    except Exception:   # WehagoError 와 어떤 모양으로 깨진 파일이든 멈추지 않는다
        res["state"] = "읽기 실패"
        res["reason"] = "매출 계산서 엑셀 읽기 실패 — %s" % name
        return res
    if source == "전자세금계산서(매출)":
        picked = rows
    else:
        picked = info["sales_rows"]
        ignored = len(rows) + info["other"] if source == "매입매출장(매출)" else 0
        if ignored:
            res["notes"].append("매입매출장(매출) 파일의 매출 아닌 줄 %d건 무시" % ignored)
    if not picked:
        res["reason"] = "%s — %s에 매출 줄이 없음" % (_SALES_NONE, name)
        return res
    res["rows"] = [_sales_row(r) for r in picked]
    res["state"], res["reason"] = "ok", ""
    ref = books.book_date if books is not None else None
    if res["file_date"] is not None and ref is not None and res["file_date"] < ref:
        res["notes"].append("매출 계산서 파일 기준일 %s — 장부 기준일 %s보다 %d일 이전" % (
            res["file_date"].isoformat(), ref.isoformat(), (ref - res["file_date"]).days))
    return res


# ───────────── 요청 대조 (D-32) ─────────────
STATUSES = ("계산서 있음", "금액 차이", "계산서 없음", "이미 지급", "연결 불가", "판단 불가")
_PAYABLE = ("미지급금", "미지급비용")
_NOT_OK_LABEL = {"자료 없음": "판단 불가(WEHAGO 자료 없음)", "경과": "판단 불가(WEHAGO 자료 경과)",
                 "머리글 다름": "판단 불가(머리글 다름)", "읽기 실패": "판단 불가(WEHAGO 읽기 실패)"}


def _signed(v):
    return ("+" if v > 0 else "") + won(v)


def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _is_payable(line):
    return _squash(line["account"]) in _PAYABLE


def _invoices(books, key, code):
    """같은 거래처·같은 코드의 매입 계산서 [(번호표, 행)]: 매입매출장이 우선, 없을 때만 전자세금계산서(매입) (W-6)."""
    for source, rows in (("매입매출장", books.ledger), ("전자세금계산서(매입)", books.einvoice)):
        found = [(i, r) for i, r in enumerate(rows) if r["vendor_norm"] == key and r["code"] == code]
        if found:
            return source, found
    return None, []


def paid_invoices(books):
    """분개장에서 이미 지급된 매입 계산서 {(출처, 번호표)} (CR-01, D-30b).

    미지급금·미지급비용 차변이 같은 거래처·같은 합계이고, 전표일자가 계산서 일자 이후·장부 기준일 이전·당일이며,
    적요에 코드가 있으면 같은 코드인 줄이 그 계산서를 지급한 줄이다. 지급 줄 하나는 계산서 하나만 지급한 것으로 본다
    (출처마다 따로, 날짜 순으로 짝짓는다). 요청과 무관하게 정해지므로 결과가 요청 순서에 따라 달라지지 않는다.
    """
    ref = books.book_date
    lines = [(line["date"], i) for i, line in enumerate(books.journal)
             if _is_payable(line) and line["debit"] is not None and line["date"] is not None
             and (ref is None or line["date"] <= ref)]
    lines.sort()
    out = set()
    for source, rows in (("매입매출장", books.ledger), ("전자세금계산서(매입)", books.einvoice)):
        used = set()
        order = sorted(range(len(rows)), key=lambda i: (rows[i]["date"] or dt.date.min, i))
        for i in order:
            inv = rows[i]
            if inv["total"] is None:
                continue
            for _, j in lines:
                line = books.journal[j]
                if j in used or line["debit"] != inv["total"] or line["vendor_norm"] != inv["vendor_norm"]:
                    continue
                if inv["date"] is not None and line["date"] < inv["date"]:
                    continue
                if line["code"] is not None and line["code"] != inv["code"]:
                    continue
                used.add(j)
                out.add((source, i))
                break
    return out


def _payment_lines(books, rq, key):
    """W-7 후보: 미지급금·미지급비용 차변이 같은 금액·같은 거래처, 전표일자가 등록일 이후 장부 기준일 이전·당일, 적요에 코드가 있으면 같은 코드 (D-35c).

    등록일을 읽지 못한 요청은 아래 한계가 없으므로 후보를 찾지 않는다 (WR-01: 이미 지급 판단 불가).
    """
    reg = rq["registered"].date() if rq.get("registered") else None
    if reg is None:
        return []
    ref = books.book_date
    out = []
    for i, line in enumerate(books.journal):
        if not _is_payable(line) or line["debit"] != rq["amount"] or line["vendor_norm"] != key:
            continue
        if line["date"] is None or line["date"] < reg:
            continue
        if ref is not None and line["date"] > ref:
            continue  # 장부 기준일 이후 전표는 아직 확정 지급으로 보지 않는다
        if line["code"] is not None and line["code"] != rq["code"]:
            continue
        out.append(i)
    return out


def _row(rq, status, label, **more):
    row = {"status": status, "label": label, "invoice_total": None, "diff": None, "schedule_amount": rq["amount"],
           "candidates": 0, "source": None, "payment": None}
    row.update(more)
    return row


def _summary(requests, rows):
    out = {}
    for status in STATUSES:
        items = [rq for rq in requests if rows[rq["번호"]]["status"] == status]
        picked = [rows[rq["번호"]] for rq in items]
        total, unknown = ssum_or_none(rq["amount"] for rq in items)
        invoices = [r["invoice_total"] for r in picked if r["invoice_total"] is not None]
        diff_status = status == "금액 차이"
        out[status] = {"count": len(items), "sum": total, "unknown": unknown,
                       "diff": sum(r["diff"] for r in picked) if diff_status else None,
                       "invoice_sum": sum(invoices) if status in ("계산서 있음", "금액 차이") else None,
                       # D-30b: 일정에 쓰는 금액 합계와, 계산서가 요청보다 적어 요청 금액으로 둔 건수
                       "schedule_sum": sum(r["schedule_amount"] for r in picked) if diff_status else None,
                       "lower": sum(1 for r in picked if r["diff"] < 0) if diff_status else None}
    return out


def match_requests(books, requests):
    """요청마다 WEHAGO 기준 상태 하나를 붙인다. 애매하면 '연결 불가'로 두어 일정에 남긴다 (W-6~W-8).

    같은 지급 줄·같은 계산서를 두 요청이 가리키면 둘 다 연결 불가이며, 결과는 요청 순서와 무관하다. books 와 requests 는 바꾸지 않는다.
    """
    seen = set()
    for rq in requests:  # 결과는 번호로 찾는다: 번호가 겹치면 한 요청의 상태가 다른 요청에 덮어써진다 (WR-07)
        if rq["번호"] in seen:
            raise ValueError("지급요청 번호가 겹침: '%s' — 요청을 구별할 수 없음" % rq["번호"])
        seen.add(rq["번호"])
    rows = {}
    if books.state != "ok":
        text = _NOT_OK_LABEL.get(books.state, _NOT_OK_LABEL["자료 없음"])
        for rq in requests:
            rows[rq["번호"]] = _row(rq, "판단 불가", text)
        return {"rows": rows, "summary": _summary(requests, rows)}

    known = set(r["vendor_norm"] for src in (books.journal, books.ledger, books.einvoice) for r in src)
    settled = paid_invoices(books)  # 이미 지급된 계산서는 어떤 요청의 근거도 아니다 (CR-01, D-30b)
    pending, pay_users, inv_users, lone_users = {}, {}, {}, {}
    for rq in requests:  # 1회전: 요청마다 후보를 모은다
        no, key = rq["번호"], norm_vendor(rq["vendor"])
        if rq["amount"] is None:
            rows[no] = _row(rq, "연결 불가", "연결 불가 (금액 미확인)")
            continue
        if key not in known:
            rows[no] = _row(rq, "연결 불가", "연결 불가 (거래처 후보 0건)")
            continue
        lines = _payment_lines(books, rq, key)
        for i in lines:
            pay_users.setdefault(i, []).append(no)
        item = {"lines": lines, "source": None, "found": [], "open": [], "exact": []}
        if not lines and rq["code"]:
            item["source"], item["found"] = _invoices(books, key, rq["code"])
            item["open"] = [(i, r) for i, r in item["found"] if (item["source"], i) not in settled]
            item["exact"] = [(i, r) for i, r in item["open"] if r["total"] == rq["amount"]]
            if len(item["exact"]) == 1:
                inv_users.setdefault((item["source"], item["exact"][0][0]), []).append(no)
            elif not item["exact"] and len(item["open"]) == 1:
                lone_users.setdefault((item["source"], item["open"][0][0]), []).append(no)
        pending[no] = item
    for rq in requests:  # 2회전: 겹침을 보고 상태를 정한다
        no = rq["번호"]
        if no in rows:
            continue
        item = pending[no]
        lines = item["lines"]
        if lines:
            if rq["status"] != "approved":
                # D-17: 사장님 승인 전에는 지급하지 않는다. 같은 금액 지급은 다른 지급일 가능성이 크다 → 일정에 둔다 (WR-01)
                rows[no] = _row(rq, "연결 불가", "연결 불가 (사장님 승인 전 요청인데 같은 금액 지급 기록 %d건)" % len(lines),
                                candidates=len(lines))
            elif len(lines) == 1 and len(pay_users[lines[0]]) == 1:
                line = books.journal[lines[0]]
                rows[no] = _row(rq, "이미 지급", "이미 지급 (분개장 %s 전표 %s)" % (line["date"].isoformat(), line["no"]),
                                candidates=1, payment={"date": line["date"], "no": line["no"], "amount": line["debit"]})
            else:
                rows[no] = _row(rq, "연결 불가", "연결 불가 (지급 후보 %d건)" % len(lines), candidates=len(lines))
            continue
        if not rq["code"]:
            rows[no] = _row(rq, "연결 불가", "연결 불가 (프로젝트 코드 없음)")
            continue
        source, found, open_, exact = item["source"], item["found"], item["open"], item["exact"]
        suffix = "" if source == "매입매출장" else " (전자세금계산서)"
        more = {"source": source, "candidates": len(found)}
        if not found:
            rows[no] = _row(rq, "계산서 없음", "계산서 없음", **more)
        elif not open_:
            # 후보 계산서가 모두 분개장에서 이미 지급됨: 이 요청의 계산서가 아니다. 일정은 인트라넷 요청 금액 (D-30b)
            rows[no] = _row(rq, "연결 불가", "연결 불가 (계산서 후보 %d건 모두 이미 지급됨)" % len(found), **more)
        elif len(exact) == 1:
            if len(inv_users[(source, exact[0][0])]) > 1:
                rows[no] = _row(rq, "연결 불가", "연결 불가 (계산서 후보 공유)", **more)
            else:
                rows[no] = _row(rq, "계산서 있음", "계산서 있음" + suffix, invoice_total=exact[0][1]["total"], diff=0, **more)
        elif not exact and len(open_) == 1 and open_[0][1]["total"] is not None:
            k = (source, open_[0][0])
            if inv_users.get(k) or len(lone_users[k]) > 1:
                # 계산서 하나는 요청 하나만: 다른 요청과 맞거나 다른 요청도 이 계산서 하나뿐이면 쓰지 않는다 (CR-01)
                rows[no] = _row(rq, "연결 불가", "연결 불가 (계산서 후보 공유)", **more)
                continue
            total = open_[0][1]["total"]
            diff = total - rq["amount"]
            # D-30a: 일정은 WEHAGO 합계. D-30b: 계산서가 요청보다 적으면 지급을 줄이지 않고 요청 금액으로 둔다
            keep = " · 일정은 인트라넷 요청 금액" if diff < 0 else ""
            rows[no] = _row(rq, "금액 차이", "금액 차이 (계산서 %s · 차액 %s%s)%s" % (won(total), _signed(diff), keep, suffix),
                            invoice_total=total, diff=diff, schedule_amount=max(total, rq["amount"]), **more)
        else:
            rows[no] = _row(rq, "연결 불가", "연결 불가 (계산서 후보 %d건)" % len(open_), **more)
    for rq in requests:  # 등록일이 없으면 이미 지급인지 알 수 없다: 그 사실을 상태 글자에 붙인다 (WR-01)
        if rq["번호"] in pending and rq.get("registered") is None and "판단 불가(등록일" not in rows[rq["번호"]]["label"]:
            rows[rq["번호"]]["label"] += " · 이미 지급 판단 불가(등록일 없음)"
    return {"rows": rows, "summary": _summary(requests, rows)}


# ───────────── 거래처별 미지급금 (D-33) ─────────────
def vendor_payables(books, requests, match, settled=()):
    """분개장 미지급금·미지급비용 거래처별 잔액(대변−차변) 대 인트라넷 대기·승인 요청 합계 (W-9, W-13).

    settled: 일정 계산이 이미 잔액에 반영된 것으로 보는 요청 id (승인 완료·예상 지급일이 잔액 기준일 이전·당일, A-3).
    이 요청들은 아직 줄 돈으로 세지 않는다 (WR-04: 같은 화면의 일정과 같은 기준).
    """
    settled = set(settled)
    out = {"rows": [], "compared": 0, "diff_count": 0, "diff_sum": 0, "unknown_count": 0, "absent_count": 0,
           "opening": False, "note": ""}
    if books.state != "ok":
        return out
    names, pay, opening = {}, {}, False
    for line in books.journal:
        names.setdefault(line["vendor_norm"], line["vendor"])
        if not _is_payable(line):
            continue
        if any(w in _squash(line["memo"]) for w in ("전기이월", "기초잔액")):
            opening = True
        entry = pay.setdefault(line["vendor_norm"], {"sum": 0, "unknown": False})
        if line["debit"] is None and line["credit"] is None:
            entry["unknown"] = True  # 금액이 전혀 없는 줄: 잔액을 알 수 없다 (0이 아니다)
        else:
            entry["sum"] += (line["credit"] or 0) - (line["debit"] or 0)
    asked, intranet_names = {}, {}
    for rq in requests:
        paid = match["rows"].get(rq["번호"], {}).get("status") == "이미 지급"
        if rq["status"] not in ("pending", "approved") or paid or rq.get("id") in settled:
            continue
        key = norm_vendor(rq["vendor"])
        intranet_names.setdefault(key, rq["vendor"])
        asked.setdefault(key, []).append(rq["amount"])
    rows = []
    for key in set(pay) | set(asked):
        total, unknown = ssum_or_none(asked.get(key, []))
        if key not in pay:  # 분개장에 이 거래처 미지급금 줄이 없다: 이름이 다르게 적혔거나 기간 밖일 수 있다 → 미확인, 0 아님 (WR-03)
            payable, reason = None, "분개장 미지급금 줄 없음"
        elif pay[key]["unknown"]:
            payable, reason = None, "분개장 미지급금 금액 미확인"
        else:
            payable, reason = pay[key]["sum"], ""
        diff = None if payable is None or unknown else payable - (total or 0)
        rows.append({"key": key, "vendor": names.get(key) or intranet_names.get(key) or "(거래처 없음)",
                     "payable": payable, "requested": total, "requested_unknown": unknown, "diff": diff, "reason": reason})
    out["compared"] = len(rows)
    shown = [r for r in rows if r["diff"] != 0]
    shown.sort(key=lambda r: (r["diff"] is None, -abs(r["diff"]) if r["diff"] is not None else 0, r["key"]))
    for r in shown:
        del r["key"]
    out["rows"] = shown
    out["diff_count"] = sum(1 for r in shown if r["diff"] is not None)
    out["diff_sum"] = sum(r["diff"] for r in shown if r["diff"] is not None)
    out["unknown_count"] = sum(1 for r in shown if r["diff"] is None)
    out["absent_count"] = sum(1 for r in shown if r["reason"] == "분개장 미지급금 줄 없음")
    out["opening"] = opening
    out["note"] = "" if opening else "기초잔액 미반영"
    return out


# ───────────── 프로젝트 (도) 원가 (D-34) ─────────────
def _link_items(links):
    """linking.link_costs 결과의 줄 -> 승인 화면 모양의 항목 (date, vendor, memo, amount + basis, label, request)."""
    return [(ln["project"], {"date": ln["date"], "vendor": ln["vendor"], "memo": ln["memo"], "amount": ln["amount"],
                             "basis": ln["basis"], "label": ln["label"], "request": ln["request"]})
            for ln in links["lines"]]


def project_costs(books, project_keys, links=None):
    """(도) 원가(계정과목에 '(도)', 계정 Code 6xxxx)의 차변−대변을 적요 [코드]로 프로젝트에 잇는다 (W-10).

    links 가 있으면(linking.link_costs 결과, D-47) 연결 규칙은 거기서 정해진 것을 그대로 쓴다: 근거가 '미연결'이 아닌 줄은
    프로젝트 목록에 없는 번호라도 그 프로젝트 아래에, '미연결' 줄은 unlinked 에 둔다. 항목은 date·vendor·memo·amount 에
    basis·label·request 가 더해진다. 이 모듈은 linking 을 가져올 수 없다(linking 이 이 모듈을 가져옴). links=None 이면 01.1 의 코드만 보는 경로다.
    """
    out = {"by_code": {}, "unlinked": {"count": 0, "sum": 0, "unknown": 0, "lines": []}}
    if books.state != "ok":
        return out
    if links is not None:
        linked, loose = {}, []
        for project, item in _link_items(links):
            if project is None:
                loose.append(item)
            else:
                linked.setdefault(project, []).append(item)
        return _cost_result(out, linked, loose)
    keys = set(str(k) for k in project_keys)
    linked, loose = {}, []
    for line in books.journal:
        if "(도)" not in _squash(line["account"]) or not re.match(r"^6\d{4}$", line["account_code"]):
            continue
        amount = None if line["debit"] is None and line["credit"] is None else (line["debit"] or 0) - (line["credit"] or 0)
        item = {"date": line["date"], "vendor": line["vendor"], "memo": line["memo"], "amount": amount}
        if line["code"] in keys:
            linked.setdefault(line["code"], []).append(item)
        else:
            loose.append(item)
    return _cost_result(out, linked, loose)


def _cost_result(out, linked, loose):
    for code, lines in linked.items():
        total, unknown = ssum_or_none(i["amount"] for i in lines)
        out["by_code"][code] = {"cost": total, "lines": lines, "unknown": unknown}
    total, unknown = ssum_or_none(i["amount"] for i in loose)
    out["unlinked"] = {"count": len(loose), "sum": total, "unknown": unknown, "lines": loose}
    return out
