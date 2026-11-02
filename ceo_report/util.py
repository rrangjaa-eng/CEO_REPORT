"""공통 도구: CSV 읽기, 숫자·날짜 해석, 금액 표시.

값이 비어 있으면 None(미확인)으로 둔다. 0으로 바꾸지 않는다.
"""
import csv
import datetime as dt
import html
import os
import re


class Issues:
    """입력 자료에서 발견한 문제를 모아 보고서 7번 묶음에 그대로 싣는다."""

    def __init__(self):
        self.items = []  # (파일, 줄, 내용)

    def add(self, file, line, msg):
        self.items.append((file, line, msg))


def read_csv(path, required, issues):
    """엑셀에서 저장한 CSV를 읽는다. UTF-8(BOM 포함)과 CP949를 모두 받는다.

    파일이 없으면 빈 목록을 돌려주고, 그 사실을 문제 목록에 남긴다.
    """
    name = os.path.basename(path)
    if not os.path.exists(path):
        issues.add(name, "-", "파일 없음 (이 묶음은 '자료 없음'으로 표시)")
        return [], False
    with open(path, "rb") as f:
        raw = f.read()
    text = None
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        issues.add(name, "-", "글자 인코딩을 읽지 못함 (UTF-8 또는 CP949로 저장 필요)")
        return [], False
    rows = list(csv.DictReader(text.splitlines()))
    header = rows[0].keys() if rows else next(csv.reader(text.splitlines()), [])
    header = [h.strip() for h in header if h is not None]
    missing = [c for c in required if c not in header]
    if missing:
        issues.add(name, 1, "필수 열 없음: " + ", ".join(missing))
    out = []
    for i, r in enumerate(rows, start=2):
        clean = {(k or "").strip(): (v or "").strip() for k, v in r.items() if k is not None}
        if not any(clean.values()):
            continue
        clean["_line"] = i
        clean["_file"] = name
        out.append(clean)
    return out, True


_NUM_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
_BLANKS = ("", "-", "미확인", "N/A", "n/a")


def _plain(value):
    """쉼표·'원'·공백을 없앤 글자."""
    return str(value).strip().replace(",", "").replace("원", "").replace(" ", "")


def is_blank(value):
    """값이 없음(빈칸·'-'·'미확인'·'N/A')이면 True. 숫자 해석과 설정 해석이 같은 기준을 쓴다."""
    return value is None or _plain(value) in _BLANKS


def num(value, issues=None, row=None, col=""):
    """'1,234,000' '-500' '(500)' → 숫자. 빈칸·'-'·'미확인' → None."""
    if is_blank(value):
        return None
    s = _plain(value)
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    if not _NUM_RE.match(s):
        if issues is not None and row is not None:
            issues.add(row["_file"], row["_line"], "%s 값이 숫자가 아님: '%s' (미확인으로 처리)" % (col, value))
        return None
    v = float(s)
    if neg:
        v = -v
    return int(round(v))


def setting_num(settings, key, default):
    """설정.csv 숫자 읽기 → (값, 사유). '50,000,000' '100%' 도 받는다.

    비었거나 항목이 없으면 (기본값, '설정 비어 있음'), 숫자가 아니면 (기본값, '숫자 아님'). 오류를 내지 않는다.
    """
    raw = settings.get(key)
    if is_blank(raw):
        return default, "설정 비어 있음"
    s = _plain(raw).replace("%", "")
    if not _NUM_RE.match(s):
        return default, "숫자 아님"
    v = float(s)
    return (int(v) if v == int(v) else v), None


def date(value, issues=None, row=None, col=""):
    """'2026-11-02' '2026.11.02' '2026/11/2' '20261102' → date. 빈칸 → None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.split(" ")[0]
    m = re.match(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})\.?$", s) or re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    if issues is not None and row is not None:
        issues.add(row["_file"], row["_line"], "%s 날짜 형식 오류: '%s' (날짜 없음으로 처리)" % (col, value))
    return None


def ssum(values):
    """None이 섞이면 합계는 숫자 부분만 더하고, 미확인 개수를 함께 돌려준다."""
    total, unknown = 0, 0
    for v in values:
        if v is None:
            unknown += 1
        else:
            total += v
    return total, unknown


def ssum_or_none(values):
    """ssum과 같지만, 값이 있는데 전부 미확인이면 합계를 0이 아니라 None(판단 불가)으로 돌려준다 (D-02)."""
    vals = list(values)
    total, unknown = ssum(vals)
    return (None if vals and unknown == len(vals) else total), unknown


def won(v, empty="미확인"):
    if v is None:
        return empty
    return ("−" if v < 0 else "") + "{:,}".format(abs(int(v)))


def man(v, empty="미확인"):
    """첫 화면용 백만원 단위 표기 (소수 1자리)."""
    if v is None:
        return empty
    x = v / 1_000_000
    return ("−" if x < 0 else "") + "{:,.1f}".format(abs(x))


def pct(a, b, empty="판단 불가"):
    if a is None or b in (None, 0):
        return empty
    return "{:.1f}%".format(a * 100.0 / b)


def d2s(d, empty="날짜 없음"):
    return d.isoformat() if d else empty


def esc(s):
    return html.escape("" if s is None else str(s))
