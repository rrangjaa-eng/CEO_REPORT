"""신한은행 대량이체 파일 (사용자 2026-11-03: 정기적으로 나가는 돈 말고 거래처 지급은 양식에 맞춰 계좌·은행·예금주까지).

양식은 ERP_PLANT8_260917 저장소의 신한 대량이체 양식과 같다: 시트 '입력정보', 머리글 9칸, 칸마다 CP949 바이트 한도, 은행은 3자리 코드.
계좌 정보는 입력/거래처계좌.csv (대표보고 창 ⑦에서 넣는다. 외장하드 입력 폴더에만 두고 저장소에는 올리지 않는다).
거래처는 위하고 거래처코드로 구분한다 (사용자 2026-11-04). 자금계획서 줄의 코드로 계좌를 찾고, 코드가 없는 줄(손으로 넣은 일정)은
이름이 계좌 목록의 한 곳과만 맞을 때 쓴다.
은행 이름을 코드로 못 풀거나 계좌·예금주가 없으면 그 줄은 파일에 넣지 않고 이유를 알린다 (짐작해서 넣으면 돈이 엉뚱한 데로 간다).
"""
import datetime as dt
import os
import re
import zipfile
from xml.sax.saxutils import escape

ACCOUNT_FILE = "거래처계좌.csv"
ACCOUNT_COLUMNS = ["거래처코드", "거래처", "은행", "계좌번호", "예금주"]
OLD_COLUMNS = ["거래처", "은행", "계좌번호", "예금주"]   # 거래처코드 칸이 없던 옛 파일도 읽는다
AMBIGUOUS = object()   # 같은 이름이 둘 이상인 거래처 (이름으로는 고르지 않는다)
SHEET = "입력정보"
HEADER = ["*입금은행", "*입금계좌", "고객관리성명", "*입금액", "출금통장표시내용", "입금통장표시내용", "입금인코드", "비고", "업체사용key"]
MAX_BYTES = {"account": 16, "holder": 20, "amount": 15, "our": 14, "their": 14, "memo": 20, "key": 20}

# 정기적으로 나가는 돈 (이체 파일에 넣지 않음): 자동이체·카드·세금·급여·예금 등
REGULAR = ("카드", "세금", "부가세", "원천세", "4대보험", "회사부담금", "급여", "인건비", "임차료", "구독료", "차입금", "정기예금",
           "보험료", "통신비", "관리비")
# 아직 요청이 아닌 계획 (이체할 돈이 아님)
PLANS = ("프로젝트 남은 예산", "프로젝트 집행계획")

BANK_CODES = {
    "신한": "088", "경남": "039", "광주": "034", "국민": "004", "기업": "003", "지역농·축협": "012", "도이치": "055", "부산": "032",
    "KDB산업": "002", "저축": "050", "새마을금고": "045", "수협": "007", "회원수협": "030", "신협": "048", "한국씨티": "027",
    "아이엠뱅크": "031", "우리": "020", "우체국": "071", "전북": "037", "제주": "035", "하나": "081", "케이뱅크": "089",
    "카카오뱅크": "090", "중국공상": "062", "비엔피파리바": "061", "BOA(BANKOFAMERICA)": "060", "HSBC": "054", "JP모건체이스": "057",
    "SC제일": "023", "산림조합": "064", "중국건설": "067", "IBK투자증권": "225", "농협": "011", "유안타증권": "209", "KB증권": "218",
    "미래에셋증권": "238", "삼성증권": "240", "한국투자증권": "243", "NH투자증권": "247", "아이엠증권": "262", "현대차증권": "263",
    "한화투자증권": "269", "하나증권": "270", "신한투자증권": "278", "메리츠증권": "287", "유진투자증권": "280", "신영증권": "291",
    "대신증권": "267", "DB금융투자": "279", "부국증권": "290", "엘에스증권주식회사": "265", "메리츠종합금융증권": "268",
    "케이프투자증권": "292", "키움증권": "264", "우리투자증권": "294", "다올투자증권": "227", "BNK투자증권": "224",
    "카카오페이증권": "288", "상상인증권": "221", "토스증권": "271", "중국은행": "063", "토스뱅크": "092", "교보증권": "261",
    "에스케이증권": "266", "NH농협증권": "289",
}
ALIASES = {
    "NH농협": "농협", "농협중앙회": "농협", "단위농협": "지역농·축협", "축협": "지역농·축협", "KB국민": "국민", "IBK기업": "기업",
    "KEB하나": "하나", "하나은행": "하나", "SC": "SC제일", "제일": "SC제일", "스탠다드차타드": "SC제일", "씨티": "한국씨티",
    "시티": "한국씨티", "산업": "KDB산업", "KDB": "KDB산업", "대구": "아이엠뱅크", "IM뱅크": "아이엠뱅크", "아이엠": "아이엠뱅크",
    "카카오": "카카오뱅크", "케이": "케이뱅크", "K뱅크": "케이뱅크", "토스": "토스뱅크", "새마을": "새마을금고",
    "MG새마을금고": "새마을금고", "신용협동조합": "신협", "수협은행": "수협", "우정사업본부": "우체국", "우체국예금보험": "우체국",
    "BOA": "BOA(BANKOFAMERICA)", "뱅크오브아메리카": "BOA(BANKOFAMERICA)", "SK증권": "에스케이증권", "IBK증권": "IBK투자증권",
}


def _norm(text):
    return re.sub(r"[\s()（）]", "", str(text or "")).upper()


_CODES = dict((_norm(k), v) for k, v in BANK_CODES.items())
_ALIAS = dict((_norm(k), _norm(v)) for k, v in ALIASES.items())


def bank_code(name):
    """은행 이름 -> 3자리 코드. 못 찾으면 None (짐작하지 않는다)."""
    v = str(name or "").strip()
    if re.match(r"^\d{3}$", v):
        return v if v in BANK_CODES.values() else None
    k = _norm(v)
    for key in (k, k[:-2] if k.endswith("은행") else None):
        if not key:
            continue
        if key in _CODES:
            return _CODES[key]
        if key in _ALIAS:
            return _CODES.get(_ALIAS[key])
    return None


def nbytes(text):
    """CP949 바이트 수 (ASCII 1, 그 밖 2)."""
    return sum(1 if ord(c) < 0x80 else 2 for c in str(text))


def cut(text, limit):
    out, n = "", 0
    for c in str(text or ""):
        w = 1 if ord(c) < 0x80 else 2
        if n + w > limit:
            break
        out, n = out + c, n + w
    return out


def _cp949_ok(text):
    try:
        str(text).encode("cp949")
        return True
    except UnicodeEncodeError:
        return False


def vendor_key(name):
    """거래처 이름 맞추기: 빈칸·(주)·주식회사를 뗀다."""
    t = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사", "", str(name or ""))
    return re.sub(r"[\s·.,\-_]", "", t)


def code_key(code):
    from .wehago import norm_code
    c = norm_code(code)
    return "#" + c if c else ""


def _read_rows(input_dir):
    """-> (줄 목록 [{거래처코드, 거래처, 은행, 계좌번호, 예금주}], 알림 또는 None). 파일이 없으면 ([], None)."""
    import csv
    path = os.path.join(input_dir, ACCOUNT_FILE)
    if not os.path.exists(path):
        return [], None
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            head = [h.strip() for h in (reader.fieldnames or [])]
            if not all(c in head for c in OLD_COLUMNS):
                return [], "%s 를 읽지 못함 (머리글: %s)" % (ACCOUNT_FILE, ",".join(ACCOUNT_COLUMNS))
            rows = []
            for r in reader:
                r = dict(((k or "").strip(), str(v or "").strip()) for k, v in r.items() if k)
                rows.append(dict((c, r.get(c, "")) for c in ACCOUNT_COLUMNS))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        return [], "%s 를 읽지 못함 (%s)" % (ACCOUNT_FILE, type(e).__name__)
    return rows, None


def read_accounts(input_dir):
    """입력/거래처계좌.csv -> ({'#코드': [계좌, ...], 이름 열쇠: 계좌 또는 AMBIGUOUS}, 알림)."""
    rows, problem = _read_rows(input_dir)
    if problem:
        return {}, [problem]
    if not rows and not os.path.exists(os.path.join(input_dir, ACCOUNT_FILE)):
        return {}, ["%s 없음 → 계좌를 채울 수 없음 (창 ⑦ 거래처 계좌에서 넣으세요)" % ACCOUNT_FILE]
    out = {}
    for r in rows:
        c = code_key(r["거래처코드"])
        if c:   # 한 코드에 여러 사람 계좌 (사업소득 프리랜서, 사용자 2026-11-04): 목록으로 둔다
            got = out.setdefault(c, [])
            if r["계좌번호"] or not got:   # 계좌 없이 코드·이름만 있는 줄(미리 등록)은 계좌가 있는 줄이 있으면 세지 않는다
                got[:] = [g for g in got if g["계좌번호"]] + [r]
        k = vendor_key(r["거래처"])
        if k:
            out[k] = r if k not in out else AMBIGUOUS
    return out, []


def save_account(input_dir, code, name, bank, number, holder):
    """한 계좌를 넣거나 고친다 (같은 거래처코드·같은 예금주면 바꿈. 한 코드에 여러 사람 계좌를 둘 수 있다).
    은행·계좌번호를 비우면 지운다 (예금주를 넣으면 그 사람만, 비우면 그 코드 전부).
    -> ('저장'|'지움', 전체 줄 수). 확인에 걸리면 ValueError (저장하지 않음)."""
    import csv
    from .wehago import norm_code
    code, name, bank = (code or "").strip(), (name or "").strip(), (bank or "").strip()
    number, holder = (number or "").strip(), (holder or "").strip()
    if not norm_code(code):
        raise ValueError("위하고 거래처코드를 넣으세요 (자금계획서의 [000101] 같은 번호)")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    rows, problem = _read_rows(input_dir)
    if problem:
        raise ValueError(problem)
    same = lambda r: code_key(r["거래처코드"]) == code_key(code) and (not holder or r["예금주"] == holder)
    rest = [r for r in rows if not same(r)]
    if not (bank or number):
        if len(rest) == len(rows):
            raise ValueError("지울 계좌가 없습니다 (거래처코드 %s%s)" % (code, " · " + holder if holder else ""))
        action = "지움"
    else:
        digits = re.sub(r"[\s-]", "", number)
        if bank_code(bank) is None:
            raise ValueError("은행 이름을 알 수 없음: '%s' (예: 신한, 국민, 기업, 농협)" % bank)
        if not digits.isdigit() or len(digits) > MAX_BYTES["account"]:
            raise ValueError("계좌번호는 숫자와 '-'만 (16자리 이하)")
        if not holder or not _cp949_ok(holder) or nbytes(holder) > MAX_BYTES["holder"]:
            raise ValueError("예금주를 넣으세요 (한글 10자 이하)")
        if not name:
            name = next((r["거래처"] for r in rows if code_key(r["거래처코드"]) == code_key(code) and r["거래처"]), "")
        # 미리 등록된 같은 코드의 빈 줄(코드·이름만)은 계좌를 넣으면 없앤다
        rest = [r for r in rest if not (code_key(r["거래처코드"]) == code_key(code) and not r["계좌번호"])]
        rest.append({"거래처코드": code, "거래처": name, "은행": bank, "계좌번호": number, "예금주": holder})
        action = "저장"
    _write_rows(input_dir, rest)
    return action, len(rest)


def _write_rows(input_dir, rows):
    import csv
    path = os.path.join(input_dir, ACCOUNT_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(ACCOUNT_COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in ACCOUNT_COLUMNS])
    os.replace(tmp, path)


def paid_vendors(journal):
    """분개장에서 매입 전표의 거래처 가운데 보통예금으로 돈이 나간 곳 (사용자 2026-11-04) -> {정규화 코드: (코드, 이름)}.
    매입 = 구분이 '매입전표'인 전표의 대변(미지급금 등) 거래처, 지급 = 보통예금(10300) 대변이 있는 전표의 차변 거래처.
    카드 거래는 뺀다: 카드 매입의 대변 거래처는 카드사이고, 이름에 '카드'가 든 코드는 넣지 않는다."""
    from collections import Counter, defaultdict
    from .wehago import norm_code
    slips = defaultdict(list)
    for r in journal:
        slips[(r["date"], r["no"])].append(r)
    bought, paid, names = set(), set(), defaultdict(Counter)
    for lines in slips.values():
        bank_out = any(ln["account_code"] == "10300" and (ln["credit"] or 0) > 0 for ln in lines)
        for ln in lines:
            c = norm_code(ln.get("vendor_code"))
            if not c:
                continue
            names[c][(ln.get("vendor_code").strip(), ln["vendor"].strip())] += 1
            if lines[0]["sort"] == "매입전표" and (ln["credit"] or 0) > 0:
                bought.add(c)
            if bank_out and (ln["debit"] or 0) > 0 and ln["account_code"] != "10300":
                paid.add(c)
    out = {}
    for c in bought & paid:
        if any("카드" in n for _, n in names[c]):
            continue
        out[c] = names[c].most_common(1)[0][0]
    return out


def register_vendors(input_dir, vendors):
    """계좌 목록에 없는 거래처코드를 코드·이름만으로 더한다 (계좌는 창 ⑦에서). -> 더한 수. 있던 줄은 건드리지 않는다."""
    rows, problem = _read_rows(input_dir)
    if problem:
        raise ValueError(problem)
    have = set(code_key(r["거래처코드"]) for r in rows)
    new = [{"거래처코드": code, "거래처": name, "은행": "", "계좌번호": "", "예금주": ""}
           for c, (code, name) in sorted(vendors.items(), key=lambda kv: kv[1][1]) if "#" + c not in have]
    if new:
        _write_rows(input_dir, rows + new)
    return len(new)


def find_account(accounts, ln):
    """이체 줄 -> (계좌 또는 None, 못 찾은 이유). 코드가 있으면 코드로만, 없으면 이름이 한 곳과 맞을 때만."""
    c = code_key(ln.get("code"))
    if c and c in accounts:
        found = accounts[c]
        if len(found) > 1:
            return None, "계좌 %d개 (%s) — 사람별 금액 필요, 은행 화면에서 나눠 넣으세요" % (
                len(found), ", ".join(r["예금주"] for r in found))
        if not found[0]["계좌번호"]:
            return None, "계좌 정보 없음 (목록에 거래처만 있음 — 창 ⑦에서 넣으세요)"
        return found[0], None
    acc = accounts.get(vendor_key(ln["vendor"]))
    if acc is AMBIGUOUS:
        return None, "같은 이름 거래처가 여럿 (거래처코드로 넣으세요)"
    if acc is not None and c and code_key(acc.get("거래처코드")) and code_key(acc.get("거래처코드")) != c:
        return None, "계좌 정보 없음 (거래처코드 %s)" % ln["code"]   # 이름만 같은 다른 거래처
    if acc is None:
        return None, "계좌 정보 없음" + (" (거래처코드 %s)" % ln["code"] if c else "")
    return acc, None


def is_regular(e):
    text = " ".join(str(e.get(k) or "") for k in ("cat", "desc"))
    return e.get("source") == "세금예상" or any(w in text for w in REGULAR)


def pick(events, start, end):
    """[start, end] 에 나갈 거래처 지급 (정기 지급·계획 제외) -> (거래처별로 합친 줄, 뺀 줄 수)."""
    lines, skipped = {}, 0
    for e in events:
        if e["io"] != "out" or e["date"] is None or not (start <= e["date"] <= end) or e.get("cat") in PLANS:
            continue
        if is_regular(e):
            skipped += 1
            continue
        name = str(e.get("desc") or "").strip()
        code = str(e.get("vendor_code") or "").strip()
        k = code_key(code) or vendor_key(name) or "?%d" % len(lines)
        ln = lines.setdefault(k, {"vendor": name, "code": code, "amount": 0, "unknown": False, "projects": [], "dates": [],
                                  "firm": True})
        if e["amount"] is None:
            ln["unknown"] = True
        else:
            ln["amount"] += e["amount"]
        if e.get("project") and e["project"] not in ln["projects"]:
            ln["projects"].append(e["project"])
        ln["dates"].append(e["date"])
        ln["firm"] = ln["firm"] and bool(e.get("firm"))
    return sorted(lines.items(), key=lambda kv: (min(kv[1]["dates"]), kv[1]["vendor"])), skipped


def _check_acc(acc, amount):
    """계좌 한 줄과 금액 -> (예금주, 계좌번호 숫자, 막는 이유 또는 None)."""
    holder = acc["예금주"]
    number = re.sub(r"[\s-]", "", acc["계좌번호"])
    why = None
    if not holder:
        why = "예금주 없음"
    elif bank_code(acc["은행"]) is None:
        why = "은행 코드 없음 (%s)" % acc["은행"]
    elif not _cp949_ok(holder) or nbytes(holder) > MAX_BYTES["holder"]:
        why = "예금주 형식·길이 오류"
    elif not number.isdigit() or len(number) > MAX_BYTES["account"]:
        why = "계좌번호 형식 오류"
    elif len(str(amount)) > MAX_BYTES["amount"]:
        why = "금액 자릿수 초과"
    return holder, number, why


def _row(bank, number, holder, amount):
    """이체 파일 9칸. 예금주는 고객관리성명에만 (사용자 2026-11-05: 은행 수취인조회로 맞춰 봄).
    출금통장표시내용·입금통장표시내용·입금인코드·비고·업체사용key 는 비운다."""
    return [bank_code(bank), number, holder, str(amount), "", "", "", "", ""]


def multi_accounts(accounts, ln):
    """거래처코드에 계좌(계좌번호 있는 줄)가 2개 이상이면 그 목록, 아니면 None."""
    found = accounts.get(code_key(ln.get("code"))) if code_key(ln.get("code")) else None
    if isinstance(found, list) and len([a for a in found if a["계좌번호"]]) > 1:
        return [a for a in found if a["계좌번호"]]
    return None


def build(events, accounts, start, end, splits=None, multi=None):
    """-> (파일 줄 [9칸], 막힌 줄 [(거래처, 금액, 이유)], 뺀 정기 지급 수).

    splits: {거래처코드 열쇠: {예금주: 금액}} — 한 코드에 예금주가 다른 계좌가 여럿일 때 사람별로 나눠 넣는다
    (사용자 2026-11-05). 합계가 지급액과 같을 때만 쓴다. multi(list)를 주면 나눌 금액이 필요한 거래처를 채운다."""
    picked, skipped = pick(events, start, end)
    rows, blocked = [], []
    splits = splits or {}
    for k, ln in picked:
        if ln["unknown"] or ln["amount"] <= 0:
            blocked.append((ln["vendor"], None if ln["unknown"] else ln["amount"], "금액 미확인"))
            continue
        many = multi_accounts(accounts, ln)
        if many:
            plan = splits.get(code_key(ln.get("code"))) or {}
            parts = [(a, plan.get(a["예금주"]) or 0) for a in many]
            if sum(v for _, v in parts) != ln["amount"] or any(v < 0 for _, v in parts):
                if multi is not None:
                    multi.append({"vendor": ln["vendor"], "code": ln.get("code") or "", "amount": ln["amount"],
                                  "holders": [a["예금주"] for a in many]})
                blocked.append((ln["vendor"], ln["amount"], "계좌 %d개 (%s) — 예금주별 금액 필요 (합계 %s원)" % (
                    len(many), ", ".join(a["예금주"] for a in many), "{:,}".format(ln["amount"]))))
                continue
            bad = [why for a, v in parts if v for why in [_check_acc(a, v)[2]] if why]
            if bad:
                blocked.append((ln["vendor"], ln["amount"], bad[0]))
                continue
            for a, v in parts:
                if v:
                    holder, number, _ = _check_acc(a, v)
                    rows.append(_row(a["은행"], number, holder, v))
            continue
        acc, missing = find_account(accounts, ln)
        if acc is None:
            blocked.append((ln["vendor"], ln["amount"], missing))
            continue
        holder, number, why = _check_acc(acc, ln["amount"])
        if why:
            blocked.append((ln["vendor"], ln["amount"], why))
            continue
        rows.append(_row(acc["은행"], number, holder, ln["amount"]))
    return rows, blocked, skipped


def missing_accounts(events, accounts, start, end):
    """[start, end] 거래처 지급 중 계좌가 없어 이체 파일에 못 넣는 곳 (사용자 2026-11-05: 그 자리에서 계좌 입력)
    -> [{vendor, code, amount, date, why}] (금액 미확인·계좌 여러 개는 빼고, 계좌·예금주가 없는 곳만)."""
    picked, _ = pick(events, start, end)
    out = []
    for k, ln in picked:
        if ln["unknown"] or ln["amount"] <= 0:
            continue
        acc, why = find_account(accounts, ln)
        if acc is not None:
            if acc.get("예금주") and acc.get("계좌번호"):
                continue
            why = "예금주 없음" if not acc.get("예금주") else "계좌번호 없음"
        elif "계좌 정보 없음" not in (why or ""):
            continue
        out.append({"vendor": ln["vendor"], "code": ln["code"], "amount": ln["amount"],
                    "date": min(ln["dates"]).isoformat(), "why": why})
    return out


def _col(i):
    return chr(ord("A") + i)


def write_xlsx(path, rows):
    """글자 칸만 있는 시트 하나짜리 xlsx (앞 0이 사라지지 않게 모두 글자)."""
    def cell(r, c, v):
        return '<c r="%s%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (_col(c), r, escape(str(v)))
    body = "".join('<row r="%d">%s</row>' % (i + 1, "".join(cell(i + 1, j, v) for j, v in enumerate(row)))
                   for i, row in enumerate([HEADER] + rows))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % body)
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>' % SHEET,
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text.encode("utf-8"))
    os.replace(tmp, path)


def make_file(input_dir, output_dir, start, end, say, asof=None, missing=None, splits=None, multi=None):
    """[start, end] 거래처 지급으로 이체 파일을 만든다. -> 만든 파일 경로 또는 None.
    missing(list)을 주면 계좌가 없어 못 넣은 거래처를 채운다 (창이 그 자리에서 계좌를 받게).
    splits·multi: 예금주가 다른 계좌가 여럿인 거래처의 사람별 금액 (build 참고)."""
    from .calc import compute
    from .data import load
    d = load(input_dir)
    R = compute(d, "weekly", asof or start - dt.timedelta(days=1))
    accounts, notes = read_accounts(input_dir)
    for n in notes:
        say(n)
    rows, blocked, skipped = build(R["events"], accounts, start, end, splits, multi)
    if missing is not None:
        missing.extend(missing_accounts(R["events"], accounts, start, end))
    say("이체 대상 %s ~ %s: 파일에 넣음 %d건 %s원, 못 넣음 %d건, 정기 지급 %d건은 뺌" % (
        start.isoformat(), end.isoformat(), len(rows), "{:,}".format(sum(int(r[3]) for r in rows)), len(blocked), skipped))
    for vendor, amount, why in blocked:
        say("  못 넣음: %s %s — %s" % (vendor, "금액 미확인" if amount is None else "{:,}원".format(amount), why))
    if not rows:
        say("파일에 넣을 줄이 없어 만들지 않았습니다")
        return None
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "신한대량이체_%s_%s.xlsx" % (start.strftime("%m%d"), end.strftime("%m%d")))
    write_xlsx(path, rows)
    say("이체 파일: %s — 신한은행 기업뱅킹 대량이체에서 불러오기 전에 금액·계좌를 한 번 더 확인하세요" % path)
    return path


def account_choices(input_dir):
    """창 ⑦ 거래처 고르기 목록 -> [(보이는 글, 코드, 이름, [계좌 줄...])]. 코드마다 한 줄, 이름 순."""
    rows, problem = _read_rows(input_dir)
    if problem:
        return []
    by = {}
    for r in rows:
        c = code_key(r["거래처코드"])
        if not c:
            continue
        g = by.setdefault(c, {"code": r["거래처코드"], "name": r["거래처"], "accs": []})
        g["name"] = g["name"] or r["거래처"]
        if r["계좌번호"]:
            g["accs"].append(r)
    out = []
    for g in sorted(by.values(), key=lambda g: (g["name"], g["code"])):
        n = len(g["accs"])
        tag = "계좌 없음" if not n else ("계좌 있음" if n == 1 else "계좌 %d개" % n)
        out.append(("%s [%s] · %s" % (g["name"] or "(이름 없음)", g["code"], tag), g["code"], g["name"], g["accs"]))
    return out
