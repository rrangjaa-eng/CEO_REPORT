"""인트라넷 지급 요청서의 '세부사항' 첫 줄 → 주간 출금 목록 상세 내역 (사용자 2026-11-05).

- 읽는 대상: 페이먼트 목록에서 관리팀 승인은 끝났고(칸 글자 '반려' 버튼) 사장님 승인 전('미승인')인 건만.
- 지급 요청서 보기(/preview/paymentwrite?...&cmd=check)를 GET 으로 읽기만 한다. 계좌·품목은 저장하지 않는다.
- 저장: 수집 스냅숏 폴더의 지급요청서.csv → 자료 변환 때 입력/지급요청서.csv 로 옮김.
- 맞추기: 프로젝트 번호(5자리) + 금액(부가세 포함)이 정확히 같을 때. 같은 후보가 여럿이면 거래처 이름으로 좁히고,
  그래도 하나가 아니면 붙이지 않는다. 같은 프로젝트 여러 건의 합이 출금 금액과 같으면 함께 붙인다.
  손으로 넣은 상세(수기)가 있으면 그것을 그대로 둔다. 세부사항이 비면 붙이지 않는다.
"""
import csv
import html
import html.parser
import os
import re

FILE = "지급요청서.csv"
COLUMNS = ["키", "프로젝트", "업체명", "금액", "세부사항"]
SOURCE = "지출결의서"
_PID = re.compile(r"(?<![0-9])([0-9]{5})(?![0-9])")


# 목록의 승인 칸 글자는 상태가 아니라 버튼 글자다 (2026-11-05 실제 화면 100건 확인, 관리팀 계정으로 볼 때):
#   관리팀승인 '승인'(승인 버튼) = 관리팀 아직 안 함 · '반려'(반려 버튼) = 관리팀 승인 끝, 사장님 전 · '수락완료' = 모두 끝
#   사장님승인 '미승인' 또는 '수락완료'
from .screen_values import ADMIN_DONE_WAITING, CEO_APPROVED as CEO_DONE  # noqa: E402  글자 목록은 한 곳 (안전-07)


def wanted(p):
    """세부사항을 읽을 페이먼트 줄인가: 관리팀 승인 끝(칸에 '반려' 버튼), 사장님 승인 전, 지급 요청서 링크가 있음."""
    return ((p.get("관리팀승인") or "").strip() in ADMIN_DONE_WAITING
            and (p.get("사장님승인") or "").strip() not in CEO_DONE and bool(p.get("_preview")))


def first_line(text):
    """세부사항 글의 첫 줄 (빈 줄은 건너뜀, 앞뒤 공백 제거). 없으면 ''."""
    for line in re.split(r"\r\n|\r|\n", text or ""):
        line = line.strip()
        if line:
            return line[:200]
    return ""


def _amount(text):
    t = re.sub(r"[,\s원]", "", str(text or ""))
    return int(t) if re.match(r"^-?[0-9]+$", t) else None


def pid_of(text):
    m = _PID.search(str(text or ""))
    return m.group(1) if m else ""


class _Preview(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.inputs, self.cells = {}, []
        self._ta, self._ta_text = None, []
        self._cell = None
        self.remark = None

    def handle_starttag(self, tag, attrs):
        a = dict((k, v or "") for k, v in attrs)
        if tag == "input" and a.get("name") and a["name"] not in self.inputs:
            self.inputs[a["name"]] = a.get("value", "")
        elif tag == "textarea":
            self._ta, self._ta_text = a.get("name", ""), []
        elif tag == "td":
            self._close()
            self._cell = []

    def _close(self):
        if self._cell is not None:
            self.cells.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None

    def handle_endtag(self, tag):
        if tag == "textarea" and self._ta is not None:
            if self._ta == "pay_remark" and self.remark is None:
                self.remark = "".join(self._ta_text)
            self._ta = None
        elif tag == "td":
            self._close()

    def handle_data(self, data):
        if self._ta is not None:
            self._ta_text.append(data)
        elif self._cell is not None:
            self._cell.append(data)


def parse_preview(text):
    """지급 요청서 화면 → {'project', 'vendor', 'amount', 'note'} (note = 세부사항 첫 줄). 못 읽은 값은 ''/None."""
    p = _Preview()
    p.feed(text or "")
    p.close()
    p._close()
    label = {}
    cells = p.cells
    for i, c in enumerate(cells[:-1]):
        k = re.sub(r"[\s:]", "", c)
        if k in ("업체명", "프로젝트명") and k not in label:
            label[k] = cells[i + 1]
    from .util import mask_rrn   # 주민번호 모양 값은 가린다 (D-36)
    return {"project": pid_of(label.get("프로젝트명", "")),
            "vendor": mask_rrn(label.get("업체명", "") or html.unescape(p.inputs.get("quo_company", ""))),
            "amount": _amount(p.inputs.get("pay_money")),
            "note": mask_rrn(first_line(p.remark))}


# ---------------------------------------------------------------------------
# 파일
# ---------------------------------------------------------------------------

def write(folder, rows):
    path = os.path.join(folder, FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r["key"], r["project"], r["vendor"], "" if r["amount"] is None else r["amount"], r["note"]])
    os.replace(tmp, path)
    return path


def read_checked(folder):
    """-> (줄 목록, None) 또는 (None, 못 읽은 까닭). 파일이 없으면 ([], None).

    2026-11-15 P5-22: 예전에는 못 읽은 파일(엑셀 저장 CP949·머리글 다름)도 '0건'으로 돌려줘, 변환이 그 0건을 입력 폴더에 써서
    있던 상세를 지웠다. 이제 UTF-8·CP949 를 모두 읽고, 그래도 못 읽으면 None 과 까닭을 돌려준다.
    """
    path = os.path.join(folder, FILE)
    if not os.path.exists(path):
        return [], None
    from .util import Issues, read_csv
    iss, info = Issues(), {}
    rows, ok = read_csv(path, COLUMNS, iss, info)
    if not ok or info.get("missing"):
        return None, "; ".join(m for _, _, m in iss.items) or "읽지 못함"
    out = []
    for r in rows:
        out.append({"key": (r["키"] or "").strip(), "project": pid_of(r["프로젝트"]), "vendor": (r["업체명"] or "").strip(),
                    "amount": _amount(r["금액"]), "note": (r["세부사항"] or "").strip()})
    return out, None


def read(folder):
    """-> [{'key','project','vendor','amount','note'}]. 없거나 못 읽으면 [] (까닭이 필요하면 read_checked)."""
    rows, _ = read_checked(folder)
    return rows or []


# ---------------------------------------------------------------------------
# 출금 일정 줄에 붙이기
# ---------------------------------------------------------------------------

def _vn(name):
    from .wehago import norm_vendor
    n = norm_vendor(name or "")
    return re.sub(r"\(.*?\)|[\s()]", "", n)


def _same_vendor(a, b):
    a, b = _vn(a), _vn(b)
    return bool(a and b and (a in b or b in a))


def attach(events, reqs):
    """출금 일정 줄에 e['detail'] = 세부사항 첫 줄 (출처 '지출결의서'). 붙인 줄 수.
    손으로 넣은 상세(수기)는 바꾸지 않는다."""
    pool = [r for r in reqs or [] if r.get("project") and r.get("amount") is not None and r.get("note")]
    if not pool:
        return 0
    used = set()
    n = 0
    outs = [e for e in events if e.get("io") == "out" and e.get("amount") is not None and pid_of(e.get("project"))
            and e.get("detail_source") != "수기" and e.get("source") != "남은 예산"]   # 예상(미요청 예산 나눔)에는 붙이지 않음
    for e in sorted(outs, key=lambda e: (e.get("date") is None, e.get("date") or 0, -(e["amount"] or 0))):   # 날짜 없는 줄은 뒤로
        pid = pid_of(e.get("project"))
        cands = [i for i, r in enumerate(pool) if i not in used and pid_of(r["project"]) == pid]
        if not cands:
            continue
        # 2차 P5-21 (2026-11-15): 두 이름이 다 있으면 같은 거래처여야 붙인다 — 같은 프로젝트·같은 금액이라는 것만으로
        # 음향 요청 상세가 조명 지급에 붙었다. 틀린 상세보다 빈 상세가 낫다 (이름을 모르는 쪽이 있으면 예전처럼 금액으로).
        named = bool(_vn(e.get("desc")))
        fits = [i for i in cands if not (named and _vn(pool[i]["vendor"])) or _same_vendor(pool[i]["vendor"], e.get("desc"))]
        pick = [i for i in fits if pool[i]["amount"] == e["amount"]]
        if len(pick) > 1:
            pick = [i for i in pick if _same_vendor(pool[i]["vendor"], e.get("desc"))]
        if len(pick) != 1:
            pick = []
            same_v = [i for i in cands if _same_vendor(pool[i]["vendor"], e.get("desc"))]
            for group in ((same_v,) if named else (same_v, cands)):
                if len(group) > 1 and sum(pool[i]["amount"] for i in group) == e["amount"]:
                    pick = group
                    break
        if not pick:
            continue
        used.update(pick)
        e["detail"] = " · ".join(dict.fromkeys(pool[i]["note"] for i in pick))
        e["detail_source"] = SOURCE
        n += 1
    return n
