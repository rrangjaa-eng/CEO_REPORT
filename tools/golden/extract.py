"""정답 예시(골든) 추출기: 지금 파이썬 프로그램이 낸 숫자를 언어와 상관없는 JSON으로 남긴다.

사례 폴더 golden/cases/<id>/ 모양:
  case.json            {"id", "title", "rules": [...], "asof": "YYYY-MM-DD", "kinds": ["weekly","monthly"], "payday": null}
  input/입력/ …        사용자가 넣는 CSV (가상)
  input/수집/ …        인트라넷 스냅숏 (가상)
  input/수집/위하고/ … 위하고 자료 (확장 JSON·엑셀, 가상)
  expected/convert.json   자료 변환이 만든 CSV (파일 이름 → 줄 목록)와 변환 결과 안내
  expected/<kind>.json    보고서 계산 결과 R (렌더 직전) + 막힘(gate) 까닭

쓰는 법:  python tools/golden/extract.py write [사례id ...]   기대값 새로 쓰기
          python tools/golden/extract.py check [사례id ...]   다시 돌려 기대값과 비교 (차이가 있으면 코드 1)
지금 프로그램 코드는 바꾸지 않는다 (읽기·실행만).
"""
import contextlib
import csv
import datetime as dt
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CASES = os.path.join(ROOT, "golden", "cases")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

GENERATED = None   # 변환 뒤 입력 폴더에서 읽을 CSV: 변환 전후로 바뀐 파일 전부 (아래에서 계산)
SKIP_R = ("auto_prev", "auto_records", "auto_profits", "lights_prev", "docs_files", "todo_prev", "week_prev", "taxret_dir")


class _Clock:
    """프로그램 안의 '오늘'을 기준일로 묶는다 (기대값이 돌린 날에 따라 바뀌지 않게). 모듈마다 'import datetime as dt' 를 쓰므로
    그 dt 이름을 today()·now() 만 바꾼 대용 모듈로 잠시 바꾼다."""

    def __init__(self, asof):
        import types
        real = dt
        fixed_now = real.datetime.combine(asof, real.time(9, 0))

        class FDate(real.date):
            @classmethod
            def today(cls):
                return asof

        class FDateTime(real.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

            @classmethod
            def today(cls):
                return fixed_now

        shim = types.ModuleType("datetime")
        shim.__dict__.update(real.__dict__)
        shim.date, shim.datetime = FDate, FDateTime
        self.shim, self.real, self.saved = shim, real, []

    def __enter__(self):
        for m in list(sys.modules.values()):
            name = getattr(m, "__name__", "") or ""
            if (name.startswith("ceo_report") or name == "ceo_report_cli") and getattr(m, "dt", None) is self.real:
                self.saved.append(m)
                m.dt = self.shim
        return self

    def __exit__(self, *exc):
        for m in self.saved:
            m.dt = self.real
        self.saved = []


def _import_all():
    """시계를 묶기 전에 프로그램 모듈을 모두 불러 둔다 (늦게 불리는 모듈도 묶이게)."""
    import importlib
    import pkgutil
    import ceo_report
    for info in pkgutil.iter_modules(ceo_report.__path__):
        if info.name in ("gui",):
            continue
        try:
            importlib.import_module("ceo_report." + info.name)
        except Exception:
            pass


def _load_report_module():
    spec = importlib.util.spec_from_file_location("ceo_report_cli", os.path.join(ROOT, "보고서.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def plain(x, tmp):
    """R 을 JSON 으로: 날짜는 ISO, 튜플·집합은 목록, 임시 경로는 <TMP>."""
    if isinstance(x, dict):
        return {str(k) if not isinstance(k, (dt.date, tuple)) else _key(k): plain(v, tmp) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v, tmp) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted((plain(v, tmp) for v in x), key=lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True))
    if isinstance(x, dt.datetime):
        return x.isoformat()
    if isinstance(x, dt.date):
        return x.isoformat()
    if isinstance(x, float) and x == int(x) and abs(x) < 2 ** 53:
        return x   # 소수는 그대로 (정수로 바꾸지 않음: 지금 프로그램의 형태 그대로 남김)
    if isinstance(x, str):
        return x.replace(tmp, "<TMP>").replace(tmp.replace("/", "\\"), "<TMP>")
    if x is None or isinstance(x, (bool, int, float)):
        return x
    if hasattr(x, "__dict__"):
        return {"__type__": type(x).__name__, **plain(vars(x), tmp)}
    return str(x)


def _key(k):
    if isinstance(k, tuple):
        return "|".join(v.isoformat() if isinstance(v, dt.date) else str(v) for v in k)
    return k.isoformat()


def _read_csv(path):
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return [row for row in csv.reader(f)]
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 인코딩을 모름: %s" % path)


def _read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _snapshot_csv(folder):
    out = {}
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if os.path.isfile(p) and name.endswith((".csv", ".json")):
            with open(p, "rb") as f:
                out[name] = f.read()
    return out


def load_case(case_dir):
    with open(os.path.join(case_dir, "case.json"), encoding="utf-8") as f:
        return json.load(f)


def extract(case_dir):
    """사례 하나를 임시 폴더에서 돌려 {파일 이름: 내용} 을 돌려준다 (기대값 파일들)."""
    case = load_case(case_dir)
    asof = dt.date.fromisoformat(case["asof"])
    now = dt.datetime.combine(asof, dt.time(0, 0))
    tmp = tempfile.mkdtemp(prefix="golden_")
    try:
        shutil.copytree(os.path.join(case_dir, "input"), os.path.join(tmp, "in"))
        input_dir = os.path.join(tmp, "in", "입력")
        collect = os.path.join(tmp, "in", "수집")
        wehago_dir = os.path.join(collect, "위하고")
        os.makedirs(wehago_dir, exist_ok=True)
        before = _snapshot_csv(input_dir)
        from ceo_report import convert
        _import_all()
        cli = _load_report_module()
        sys.modules["ceo_report_cli"] = cli
        clock = _Clock(asof)
        with clock, contextlib.redirect_stdout(io.StringIO()):
            res = convert.run(input_dir, collect, wehago_dir, asof, now, stamp="GOLDEN", ran_at=now)
        after = _snapshot_csv(input_dir)
        changed = sorted(n for n in after if before.get(n) != after[n])
        conv = {"code": res.code, "lines": res.lines,
                "files": {n: _read_csv(os.path.join(input_dir, n)) for n in changed if n.endswith(".csv")},
                "json": {n: _read_json(os.path.join(input_dir, n)) for n in changed if n.endswith(".json")}}
        files = {"convert.json": plain(conv, tmp)}
        for kind in case.get("kinds", ["weekly", "monthly"]):
            got = {}

            def fake_render(R, mode, _got=got):
                if mode == "mgmt":
                    _got["R"] = R
                return ""

            real_problems = None
            from ceo_report import gate
            real_problems = gate.problems

            def spy_problems(R, _got=got):
                _got["stop"] = real_problems(R)
                return _got["stop"]

            out_dir = os.path.join(tmp, "out_" + kind)
            argv = ["주간" if kind == "weekly" else "월간", "--기준일", asof.isoformat(), "--입력", input_dir,
                    "--출력", out_dir, "--pdf", "안함", "--팀장용", "안함"]
            if case.get("payday"):
                argv += ["--출금일", case["payday"]]
            env = {k: v for k, v in os.environ.items() if k != gate.TEST_OFF}
            with _Clock(asof), mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(cli, "render", fake_render), \
                    mock.patch.object(gate, "problems", spy_problems), \
                    contextlib.redirect_stdout(io.StringIO()) as said:
                rc = cli.main(argv)
            R = got.get("R")
            body = {"rc": rc, "stop": got.get("stop"), "said": said.getvalue().splitlines(),
                    "R": None if R is None else {k: v for k, v in R.items() if not k.startswith("_") and k not in SKIP_R}}
            files["%s.json" % kind] = plain(body, tmp)
        return files
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def write(case_dir):
    exp = os.path.join(case_dir, "expected")
    shutil.rmtree(exp, ignore_errors=True)
    os.makedirs(exp)
    for name, body in extract(case_dir).items():
        with open(os.path.join(exp, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(body))


def check(case_dir):
    """-> 차이 목록 (같으면 [])."""
    diffs = []
    exp = os.path.join(case_dir, "expected")
    got = extract(case_dir)
    names = set(got) | set(os.listdir(exp) if os.path.isdir(exp) else [])
    for name in sorted(names):
        p = os.path.join(exp, name)
        if name not in got:
            diffs.append("%s: 기대값만 있음" % name)
            continue
        if not os.path.exists(p):
            diffs.append("%s: 기대값 파일 없음" % name)
            continue
        with open(p, encoding="utf-8") as f:
            want = f.read()
        have = dumps(got[name])
        if want != have:
            import difflib
            d = list(difflib.unified_diff(want.splitlines(), have.splitlines(), "기대", "실제", n=1, lineterm=""))
            diffs.append("%s: 다름\n%s" % (name, "\n".join(d[:40])))
    return diffs


def case_dirs(ids=None):
    if not os.path.isdir(CASES):
        return []
    all_ids = sorted(n for n in os.listdir(CASES) if os.path.isfile(os.path.join(CASES, n, "case.json")))
    return [os.path.join(CASES, i) for i in (ids or all_ids)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("write", "check"):
        print(__doc__)
        return 2
    bad = 0
    for d in case_dirs(argv[1:]):
        if argv[0] == "write":
            write(d)
            print("썼음:", os.path.basename(d))
        else:
            diffs = check(d)
            print(("같음: " if not diffs else "다름: ") + os.path.basename(d), *diffs)
            bad += bool(diffs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
