"""WEHAGO 장부 엑셀(분개장·매입매출장·전자세금계산서(매입))을 표준 라이브러리로 읽고 인트라넷 요청과 대조한다. 실제 파일은 git 제외 폴더에만 둔다."""
import datetime as dt
import decimal
import os
import posixpath
import re
import unicodedata
import zipfile
import zlib
import xml.etree.ElementTree as ET

from .approval import parse_registered, project_code  # noqa: F401  (parse_registered: 지급 확인 단계에서 쓴다)
from .util import is_blank, ssum_or_none, won
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
_RRN_RE = re.compile(r"\d{6}[- ]?\d{7}")  # 앞뒤 숫자 제한 없음: 더 긴 숫자 안의 6+7자리도 가린다 (D-36, W-11)


def mask_rrn(text):
    """주민번호 모양(6자리 + 선택 '-'/공백 + 7자리, 일곱째 자리 수 무관)을 '******-*******'로 바꾼다."""
    return _RRN_RE.sub("******-*******", text or "")


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
    """합계·소계·일계·월계·누계로 시작하거나 '거래처별 소계'를 포함한 칸이 하나라도 있는 요약 줄 (D-35c)."""
    for c in row:
        s = c.strip()
        if "거래처별소계" in re.sub(r"\s+", "", s):
            return True
        if s.lstrip("[]()<>【】「」 \t").startswith(_SUBTOTAL):
            return True
    return False


def read_book(path, kind, file_date=None, asof=None):
    """한 파일을 머리글 이름으로 읽어 (행 dict 목록, 요약)을 돌려준다. 머리글이 다르면 HeaderMismatch."""
    name = os.path.basename(path)
    rows = read_xlsx(path)
    cols, extra = _check_header(rows, kind, name)
    year_ref = (file_date or asof) if kind == "전자세금계산서(매입)" else None  # 'MM-DD'는 전자세금계산서만 (W-12)
    d1904 = rows.date1904
    date_col = {"분개장": "전표일자", "매입매출장": "전표일자", "전자세금계산서(매입)": "일자"}[kind]

    def txt(row, header, n=0):
        return mask_rrn(row[cols[header][n]].strip())

    out, last = [], None
    info = {"last_date": None, "rows": 0, "skipped": 0, "undated": 0, "sales": 0, "other": 0, "after_ref": 0,
            "extra_columns": list(extra), "extra_note": ("추가 열 무시: " + ", ".join(extra)) if extra else ""}
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            info["skipped"] += 1
            continue
        date = _parse_date(row[cols[date_col][0]], d1904, year_ref)
        if _is_subtotal(row):
            info["skipped"] += 1  # 합계·소계·일계·월계·누계 줄: 저장하지 않고 마지막 날짜·날짜 없음에도 넣지 않는다 (W-14, D-35c)
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
                    "credit": _amount(row[cols["대변"][0]]), "vendor": txt(row, "거래처"), "memo": txt(row, "적요")}
            item["code"] = project_code(item["memo"])
        elif kind == "매입매출장":
            sort = row[cols["구분"][0]].strip()
            if sort != "매입":  # 매출 줄은 세지만 남기지 않는다. 사업자(주민)번호 칸은 아예 읽지 않는다 (W-11)
                info["sales" if sort == "매출" else "other"] += 1
                continue
            item = {"date": date, "no": txt(row, "번호"), "vendor": txt(row, "거래처"), "item": txt(row, "품명"),
                    "supply": _amount(row[cols["공급가액"][0]]), "vat": _amount(row[cols["부가세"][0]]),
                    "total": _amount(row[cols["합계"][0]])}
            item["code"] = project_code(item["item"])
        else:
            item = {"date": date, "vendor": txt(row, "거래처"), "item": txt(row, "품명"),
                    "supply": _amount(row[cols["공급가액"][0]]), "vat": _amount(row[cols["부가세"][0]]),
                    "total": _amount(row[cols["합계"][0]]), "debit_account": txt(row, "차변계정"),
                    "slip_state": txt(row, "전표상태")}
            item["code"] = project_code(item["item"])
        item["vendor_norm"] = norm_vendor(item["vendor"])
        out.append(item)
    info["last_date"] = last
    return out, info


def _file_date(name):
    """파일 이름에서 '_' 뒤 첫 8자리 숫자(YYYYMMDD)."""
    for m in re.finditer(r"_(\d+)", name):
        if len(m.group(1)) == 8:
            try:
                return dt.date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:]))
            except ValueError:
                continue
    return None


def _kind_of(name):
    """파일 이름이 속하는 종류와 읽어도 되는지. 매출 전자세금계산서는 종류는 같지만 읽지 않는다 (W-1)."""
    if "매입매출장" in name:
        return "매입매출장", True
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


def load_books(folder, asof, stale_days):
    """폴더의 세 종류 파일을 골라 읽는다. 없음·오래됨·머리글 다름·읽기 실패는 state 로 알리고 예외를 내지 않는다 (W-1~W-4)."""
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
        if ext == ".xlsx":
            (candidates[kind] if readable else unused).append(n)
        elif readable and ext in (".xls", ".csv"):
            lookalikes[kind].append(n)
    chosen = {}
    for kind in KINDS:
        if candidates[kind]:
            ranked = sorted(candidates[kind], key=lambda n: (_file_date(n) or dt.date.min,
                                                             _mtime(os.path.join(folder, n)), n))
            chosen[kind] = ranked[-1]
            unused.extend(ranked[:-1])
    books.unused = sorted(unused)

    staged, mismatches, failures = {}, [], []
    for kind in KINDS:
        name = chosen.get(kind)
        if name is None:
            continue
        fdate = _file_date(name)
        entry = {"name": name, "file_date": fdate, "last_date": None, "ref_date": fdate, "rows": 0, "skipped": 0,
                 "undated": 0, "after_ref": 0, "extra_columns": [], "extra_note": ""}
        books.files[kind] = entry
        try:
            rows, info = read_book(os.path.join(folder, name), kind, fdate, asof)
        except HeaderMismatch as e:
            entry["error"] = str(e)
            mismatches.append(e)
        except WehagoError as e:
            entry["error"] = str(e)
            failures.append("%s 읽기 실패 — %s" % (name, e))
        except Exception:  # 깨진 파일이 어떤 모양이든 화면을 멈추지 않는다
            entry["error"] = "엑셀 내용을 읽을 수 없음"
            failures.append("%s 읽기 실패 — 엑셀 내용을 읽을 수 없음" % name)
        else:
            entry.update(dict((k, info[k]) for k in ("last_date", "rows", "skipped", "undated", "sales", "other",
                                                     "after_ref", "extra_columns", "extra_note")))
            entry["ref_date"] = fdate or info["last_date"]
            staged[kind] = rows
    refs = [books.files[k]["ref_date"] for k in KINDS if k in books.files and books.files[k]["ref_date"]]
    books.book_date = min(refs) if refs else None
    books.after_ref = sum(e["after_ref"] for e in books.files.values())

    missing = [k for k in KINDS if k not in chosen]
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
        ref_all = [books.files[k]["ref_date"] for k in KINDS]
        if None in ref_all:
            books.state = "경과"
            books.reason = "장부 기준일을 알 수 없음 (파일 이름에 날짜가 없고 전표일자도 없음)"
        else:
            late = (asof - books.book_date).days
            if late > stale_days:
                oldest = [k for k in KINDS if books.files[k]["ref_date"] == books.book_date][0]
                books.state = "경과"
                books.reason = "장부 기준일 %s, 기준일보다 %d일 이전 (%s)" % (books.book_date.isoformat(), late, oldest)
            else:
                books.state = "ok"
    if books.state == "ok":  # 부분 사용 없음: ok 일 때만 행을 준다 (D-35a)
        books.journal, books.ledger, books.einvoice = staged["분개장"], staged["매입매출장"], staged["전자세금계산서(매입)"]
    return books


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


def _payment_lines(books, rq, key):
    """W-7 후보: 미지급금·미지급비용 차변이 같은 금액·같은 거래처, 전표일자가 등록일 이후 장부 기준일 이전·당일, 적요에 코드가 있으면 같은 코드 (D-35c)."""
    reg = rq["registered"].date() if rq.get("registered") else None
    ref = books.book_date
    out = []
    for i, line in enumerate(books.journal):
        if not _is_payable(line) or line["debit"] != rq["amount"] or line["vendor_norm"] != key:
            continue
        if line["date"] is None or (reg is not None and line["date"] < reg):
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
        out[status] = {"count": len(items), "sum": total, "unknown": unknown,
                       "diff": sum(r["diff"] for r in picked) if status == "금액 차이" else None,
                       "invoice_sum": sum(invoices) if status in ("계산서 있음", "금액 차이") else None}
    return out


def match_requests(books, requests):
    """요청마다 WEHAGO 기준 상태 하나를 붙인다. 애매하면 '연결 불가'로 두어 일정에 남긴다 (W-6~W-8).

    같은 지급 줄·같은 계산서를 두 요청이 가리키면 둘 다 연결 불가이며, 결과는 요청 순서와 무관하다. books 와 requests 는 바꾸지 않는다.
    """
    rows = {}
    if books.state != "ok":
        text = _NOT_OK_LABEL.get(books.state, _NOT_OK_LABEL["자료 없음"])
        for rq in requests:
            rows[rq["번호"]] = _row(rq, "판단 불가", text)
        return {"rows": rows, "summary": _summary(requests, rows)}

    known = set(r["vendor_norm"] for src in (books.journal, books.ledger, books.einvoice) for r in src)
    pending, pay_users, inv_users = {}, {}, {}
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
        item = {"lines": lines, "source": None, "found": [], "exact": []}
        if not lines and rq["code"]:
            item["source"], item["found"] = _invoices(books, key, rq["code"])
            item["exact"] = [(i, r) for i, r in item["found"] if r["total"] == rq["amount"]]
            if len(item["exact"]) == 1:
                inv_users.setdefault((item["source"], item["exact"][0][0]), []).append(no)
        pending[no] = item
    for rq in requests:  # 2회전: 겹침을 보고 상태를 정한다
        no = rq["번호"]
        if no in rows:
            continue
        item = pending[no]
        lines = item["lines"]
        if lines:
            if len(lines) == 1 and len(pay_users[lines[0]]) == 1:
                line = books.journal[lines[0]]
                rows[no] = _row(rq, "이미 지급", "이미 지급 (분개장 %s 전표 %s)" % (line["date"].isoformat(), line["no"]),
                                candidates=1, payment={"date": line["date"], "no": line["no"], "amount": line["debit"]})
            else:
                rows[no] = _row(rq, "연결 불가", "연결 불가 (지급 후보 %d건)" % len(lines), candidates=len(lines))
            continue
        if not rq["code"]:
            rows[no] = _row(rq, "연결 불가", "연결 불가 (프로젝트 코드 없음)")
            continue
        source, found, exact = item["source"], item["found"], item["exact"]
        suffix = "" if source == "매입매출장" else " (전자세금계산서)"
        more = {"source": source, "candidates": len(found)}
        if not found:
            rows[no] = _row(rq, "계산서 없음", "계산서 없음", **more)
        elif len(exact) == 1:
            if len(inv_users[(source, exact[0][0])]) > 1:
                rows[no] = _row(rq, "연결 불가", "연결 불가 (계산서 후보 공유)", **more)
            else:
                rows[no] = _row(rq, "계산서 있음", "계산서 있음" + suffix, invoice_total=exact[0][1]["total"], diff=0, **more)
        elif not exact and len(found) == 1 and found[0][1]["total"] is not None:
            total = found[0][1]["total"]
            diff = total - rq["amount"]
            rows[no] = _row(rq, "금액 차이", "금액 차이 (계산서 %s · 차액 %s)%s" % (won(total), _signed(diff), suffix),
                            invoice_total=total, diff=diff, schedule_amount=total, **more)  # D-30a: 일정은 WEHAGO 합계
        else:
            rows[no] = _row(rq, "연결 불가", "연결 불가 (계산서 후보 %d건)" % len(found), **more)
    return {"rows": rows, "summary": _summary(requests, rows)}


# ───────────── 거래처별 미지급금 (D-33) ─────────────
def vendor_payables(books, requests, match):
    """분개장 미지급금·미지급비용 거래처별 잔액(대변−차변) 대 인트라넷 대기·승인 요청 합계 (W-9, W-13)."""
    out = {"rows": [], "compared": 0, "diff_count": 0, "diff_sum": 0, "unknown_count": 0, "opening": False, "note": ""}
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
        if rq["status"] not in ("pending", "approved") or paid:
            continue
        key = norm_vendor(rq["vendor"])
        intranet_names.setdefault(key, rq["vendor"])
        asked.setdefault(key, []).append(rq["amount"])
    rows = []
    for key in set(pay) | set(asked):
        total, unknown = ssum_or_none(asked.get(key, []))
        payable = None if key in pay and pay[key]["unknown"] else (pay[key]["sum"] if key in pay else 0)
        diff = None if payable is None or unknown else payable - (total or 0)
        rows.append({"key": key, "vendor": names.get(key) or intranet_names.get(key) or "(거래처 없음)",
                     "payable": payable, "requested": total, "requested_unknown": unknown, "diff": diff})
    out["compared"] = len(rows)
    shown = [r for r in rows if r["diff"] != 0]
    shown.sort(key=lambda r: (r["diff"] is None, -abs(r["diff"]) if r["diff"] is not None else 0, r["key"]))
    for r in shown:
        del r["key"]
    out["rows"] = shown
    out["diff_count"] = sum(1 for r in shown if r["diff"] is not None)
    out["diff_sum"] = sum(r["diff"] for r in shown if r["diff"] is not None)
    out["unknown_count"] = sum(1 for r in shown if r["diff"] is None)
    out["opening"] = opening
    out["note"] = "" if opening else "기초잔액 미반영"
    return out


# ───────────── 프로젝트 (도) 원가 (D-34) ─────────────
def project_costs(books, project_keys):
    """(도) 원가(계정과목에 '(도)', 계정 Code 6xxxx)의 차변−대변을 적요 [코드]로 프로젝트에 잇는다 (W-10)."""
    out = {"by_code": {}, "unlinked": {"count": 0, "sum": 0, "unknown": 0, "lines": []}}
    if books.state != "ok":
        return out
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
    for code, lines in linked.items():
        total, unknown = ssum_or_none(i["amount"] for i in lines)
        out["by_code"][code] = {"cost": total, "lines": lines, "unknown": unknown}
    total, unknown = ssum_or_none(i["amount"] for i in loose)
    out["unlinked"] = {"count": len(loose), "sum": total, "unknown": unknown, "lines": loose}
    return out
