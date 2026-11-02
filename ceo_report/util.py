"""공통 도구: CSV 읽기, 숫자·날짜 해석, 금액 표시.

값이 비어 있으면 None(미확인)으로 둔다. 0으로 바꾸지 않는다.
"""
import csv
import datetime as dt
import html
import io
import os
import re


class Issues:
    """입력 자료에서 발견한 문제를 모아 보고서 7번 묶음에 그대로 싣는다."""

    def __init__(self):
        self.items = []  # (파일, 줄, 내용)

    def add(self, file, line, msg):
        self.items.append((file, line, msg))


TITLE_ROWS = 5  # 머리글 위 제목 줄을 이만큼까지 건너뛴다


def read_csv(path, required, issues, info=None):
    """엑셀에서 저장한 CSV를 읽는다. UTF-8(BOM 포함)과 CP949를 모두 받는다.

    파일이 없으면 빈 목록을 돌려주고, 그 사실을 문제 목록에 남긴다.
    info(dict)를 주면 info['missing']에 머리글에 없는 필수 열 목록을 넣는다.
    """
    name = os.path.basename(path)
    if info is not None:
        info["missing"] = list(required)
    if not os.path.exists(path):
        issues.add(name, "-", "파일 없음 (이 묶음은 '자료 없음'으로 표시)")
        return [], False
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:  # Windows에서 엑셀이 파일을 열어 두면 PermissionError
        issues.add(name, "-", "파일을 열 수 없음 (엑셀에서 열려 있으면 닫고 다시 실행): %s" % (e.strerror or type(e).__name__))
        return [], False
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
    # 디코딩한 글자를 줄바꿈 그대로(newline="") csv 모듈에 넘긴다. splitlines()는 \x0b \x1c \x85 \u2028 같은 문자에서도
    # 줄을 갈라 칸 안의 글자를 망가뜨리고 줄 번호도 어긋나게 한다.
    reader = csv.reader(io.StringIO(text, newline=""))
    records, prev_end = [], 0
    for cells in reader:
        start, prev_end = prev_end + 1, reader.line_num  # 이 기록이 시작한 실제 파일 줄 (칸 안 줄바꿈·빈 줄 포함)
        if not cells:
            continue
        records.append((start, cells))
    # 머리글: 첫 줄. 엑셀에서 표 위에 제목 줄을 두고 저장했으면 필수 열이 모두 있는 줄(앞 TITLE_ROWS 줄 안)을 머리글로 쓴다.
    at = 0
    if records and not all(c in [h.strip() for h in records[0][1]] for c in required):
        for i, (_, cells) in enumerate(records[1:TITLE_ROWS + 1], 1):
            if all(c in [h.strip() for h in cells] for c in required):
                at = i
                issues.add(name, records[i][0], "머리글 위 제목 줄 %d줄을 건너뛰고 %d번째 줄을 머리글로 읽음" % (at, records[i][0]))
                break
    header = [h.strip() for h in records[at][1]] if records else []
    records = records[at + 1:]
    missing = [c for c in required if c not in header]
    if info is not None:
        info["missing"] = missing
    if missing:
        issues.add(name, 1, "필수 열 없음: " + ", ".join(missing))
    out = []
    for line, cells in records:
        clean = {}
        for k, v in zip(header, cells):  # 헤더보다 많은 칸은 버린다 (DictReader와 같음)
            clean[k] = (v or "").strip()
        for k in header[len(cells):]:
            clean.setdefault(k, "")
        if not any(clean.values()):
            continue
        clean["_line"] = line
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
    """HTML 글자 칸. 주민번호 모양은 먼저 가리고(mask_rrn) 나서 escape 한다 (D-36: 두 화면의 모든 글자 칸)."""
    return html.escape(mask_rrn(s))


# 주민번호 모양: 6자리 + (공백) + 선택 구분자(-, 여러 대시, 점, 빗금, 전각 포함) + (공백) + 7자리.
# 앞뒤 숫자 제한 없음: 더 긴 숫자 안의 6+7자리도 가린다 (D-36 과잉 가림 허용, W-11, WR-08).
# 날짜(2026-10-31)·쉼표 금액·전화번호(010-1234-5678)는 6자리 연속 숫자가 없어 걸리지 않는다.
_RRN_RE = re.compile("\\d{6}\\s*[-‐‑‒–—―−﹣－.．/／]?\\s*\\d{7}")


def mask_rrn(text):
    """주민번호 모양 글자를 '******-*******'로 바꾼다. None 은 빈 글자. 화면·CSV·stdout 으로 나가는 글자에 쓴다 (D-36)."""
    return _RRN_RE.sub("******-*******", "" if text is None else str(text))
