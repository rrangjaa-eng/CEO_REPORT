"""정답 예시 사례의 입력 폴더를 만든다. 모두 가상 자료 (tests/ 의 가상 자료 도구를 그대로 씀).

python tools/golden/build.py [사례id ...]   (비우면 전부) → golden/cases/<id>/case.json 과 input/ 을 새로 씀
사례 함수는 CASES 에 등록한다: fn(input_dir, collect, wehago_dir) -> case.json 내용(dict, id·input 제외)
"""
import datetime as dt
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS = os.path.join(ROOT, "tests")
for p in (ROOT, TESTS):
    if p not in sys.path:
        sys.path.insert(0, p)
GOLDEN = os.path.join(ROOT, "golden", "cases")

CASES = {}


def case(fn):
    CASES[fn.__name__.replace("case_", "")] = fn
    return fn


# ───────────── 공용 도구 ─────────────
def sample_input(input_dir):
    """tools/make_sample.py 의 가상 입력 (설정·계좌잔액·지급계획 등). 저장소 안 폴더라 '실제 입력' 확인을 거치지 않고 바로 씀."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_sample", os.path.join(ROOT, "tools", "make_sample.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        m.write_sample(os.path.join(tmp, "s"))   # 저장소 안 '입력' 폴더에는 바로 쓰지 않는 안전장치가 있어 임시 폴더를 거침
        shutil.copytree(os.path.join(tmp, "s"), input_dir, dirs_exist_ok=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_json(folder, name, doc):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


PLAN_COLS = ["date", "yn_inout", "cd_fitem", "nm_fitem", "cd_trade", "nm_trade", "mn_fplan", "rmk_fplan", "str_refer", "da_fplan"]


def plan_doc(rows, months, frm, to, taken, company="(샘플) 플랜트에이트"):
    """확장이 저장하는 자금계획 JSON (background.js planResult 모양)."""
    return {"종류": "자금계획", "형식": 1, "수집시각": taken, "회사": company,
            "기간": {"from": frm, "to": to, "months": len(months)}, "조회한달": months, "오류": [],
            "줄수": len(rows), "열": PLAN_COLS, "줄": rows}


def plan_row(day, inout, vendor_code, vendor, amount, memo="", item=("102", "미지급금 지급")):
    if inout == "입금" and item == ("102", "미지급금 지급"):
        item = ("601", "외상대금 회수")
    return [day, inout, item[0], item[1], vendor_code, vendor, amount, memo, "매입매출", day[-2:]]


def base_books(input_dir, collect, wehago_dir, journal=None, ledger=None, sales=None, snapshot=True,
               journal_stamp="261031", journal_start="20260101", journal_end="20261031"):
    """가상 회사 한 곳: 샘플 입력 + 분개장(확장 JSON) + 매입매출장·전자세금계산서(엑셀) + 매출 계산서 + 인트라넷 스냅숏."""
    from test_wehago import write_fake_books
    from test_convert import FAKE_PL_JOURNAL
    from test_convert_invoices import PURCHASE_LEDGER, SALES_EINVOICE, write_sales
    from test_journal_json import auto_json
    from test_approval import write_fake_snapshot
    sample_input(input_dir)
    os.makedirs(wehago_dir, exist_ok=True)
    jr = FAKE_PL_JOURNAL if journal is None else journal
    write_fake_books(wehago_dir, journal=jr, ledger=PURCHASE_LEDGER if ledger is None else ledger, drop=("분개장",))
    doc = auto_json(jr, start=journal_start, end=journal_end)
    doc["회사"] = "(샘플) 플랜트에이트"
    write_json(wehago_dir, "%s 분개장 자동수집.json" % journal_stamp, doc)
    write_sales(wehago_dir, SALES_EINVOICE if sales is None else sales)
    if snapshot:
        write_fake_snapshot(collect)


BASE_PLAN = [
    plan_row("20261106", "지급", "000-00-00002", "㈜가상제작", 165000000, "매입 - 가상 전시 제작"),
    plan_row("20261113", "지급", "000-00-00001", "(주)가상음향", 44000000, "매입 - 가상 컨퍼런스 음향"),
    plan_row("20261120", "입금", "C202", "가상고객D", 82500000, "매출 - 가상 전시부스 잔금"),
    plan_row("20261204", "지급", "000-00-00003", "주식회사 가상부스", 49500000, "매입 - 가상 전시부스"),
]


# ───────────── 사례 ─────────────
@case
def case_base(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir)
    write_json(wehago_dir, "261101 자금계획 자동수집.json",
               plan_doc(BASE_PLAN, ["202610", "202611", "202612"], "20261001", "20261231", "2026-11-01 09:00:00"))
    return {"title": "기본 가상 회사 (2026-11-02 기준, 모든 자료 있음)", "rules": ["F11"], "asof": "2026-11-02",
            "kinds": ["weekly", "monthly"]}


def _load_groups():
    """규칙 묶음별 사례 파일 (cases_d.py 자료 규칙, cases_f.py 자금 규칙, cases_u.py 사용자 규칙). 각 파일은 @case 를 쓴다."""
    import importlib
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    sys.modules.setdefault("build", sys.modules[__name__])   # 묶음 파일의 'from build import case' 가 같은 CASES 를 쓰게
    for name in ("cases_d", "cases_f", "cases_u"):
        if os.path.exists(os.path.join(here, name + ".py")):
            importlib.import_module(name)


def build(cid):
    d = os.path.join(GOLDEN, cid)
    shutil.rmtree(d, ignore_errors=True)
    inp = os.path.join(d, "input")
    input_dir, collect = os.path.join(inp, "입력"), os.path.join(inp, "수집")
    wehago_dir = os.path.join(collect, "위하고")
    os.makedirs(input_dir)
    os.makedirs(wehago_dir)
    meta = CASES[cid](input_dir, collect, wehago_dir)
    meta = dict(meta, id=cid)
    with open(os.path.join(d, "case.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return d


def main(argv=None):
    _load_groups()
    ids = (sys.argv[1:] if argv is None else argv) or sorted(CASES)
    for cid in ids:
        build(cid)
        print("만듦:", cid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
