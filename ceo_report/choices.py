"""회사가 고르는 자금 선택 (A4·A5, 2026-11-17 사용자 '추가 기능은 전부'): 입력/자금선택.csv (항목, 값, 바꾼 날).

· 법인세분납: '예'면 3월 말 법인세 중 법이 허용하는 만큼을 2달 뒤(중소기업)로 나눠 일정에 넣는다 (corptax.installment).
· 예금금리: 당분간 안 쓸 돈의 예금 이자 어림에 쓰는 연 금리(%) — 비우면 이자는 계산하지 않는다 (가정을 넣지 않음).
설정.csv 는 읽기만 하므로(D-39) 따로 둔다. 값이 없으면 아무것도 바꾸지 않는다.
"""
import csv
import datetime as dt
import os

from .util import open_text as _open_text

FILE = "자금선택.csv"
COLUMNS = ["항목", "값", "바꾼 날"]
KEYS = {"법인세분납": ("예", "아니오"), "예금금리": None}


def read(input_dir):
    out = {}
    path = os.path.join(input_dir, FILE) if input_dir else None
    if not path or not os.path.exists(path):
        return out
    try:
        with _open_text(path) as f:
            for r in csv.DictReader(f):
                k = (r.get("항목") or "").strip()
                if k in KEYS:
                    out[k] = (r.get("값") or "").strip()
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return out


def installment(input_dir):
    return read(input_dir).get("법인세분납") == "예"


def rate(input_dir):
    """예금 연 금리 (0.03 꼴) 또는 None."""
    t = read(input_dir).get("예금금리", "").replace("%", "").strip()
    try:
        v = float(t)
    except ValueError:
        return None
    if v <= 0 or v > 30:
        return None
    return v / 100.0


def save(input_dir, values, today=None):
    """values = {항목: 값}. 고를 수 있는 값만 받는다 -> 저장한 개수."""
    cur = read(input_dir)
    path0 = os.path.join(input_dir, FILE) if input_dir else None
    if path0 and os.path.exists(path0) and os.path.getsize(path0) > 0 and not cur:
        # 2차 전수조사 P5 (2026-11-18): 못 읽은 파일을 빈 것으로 보고 새로 쓰면 예전 선택이 지워짐 → 한 번 더 엄격히 읽어 보고 멈춤
        try:
            with _open_text(path0) as f:
                list(csv.DictReader(f))
        except (OSError, csv.Error, UnicodeDecodeError) as e:
            raise ValueError("%s 를 읽지 못해 저장하지 않았습니다 (%s) — 파일이 열려 있으면 닫고 다시 하세요" % (FILE, type(e).__name__))
    for k, v in values.items():
        if k not in KEYS:
            raise ValueError("모르는 항목: %s" % k)
        v = str(v or "").strip()
        if KEYS[k] and v and v not in KEYS[k]:
            raise ValueError("%s: '%s'는 고를 수 있는 값이 아님 (%s)" % (k, v, "/".join(KEYS[k])))
        if k == "예금금리" and v:
            try:
                f = float(v.replace("%", ""))
            except ValueError:
                raise ValueError("예금금리: 숫자로 넣어 주세요 (예: 3.0)")
            if not 0 < f <= 30:
                raise ValueError("예금금리: 0보다 크고 30 이하 (%)")
        cur[k] = v
    os.makedirs(input_dir, exist_ok=True)
    day = (today or dt.date.today()).isoformat()
    tmp = os.path.join(input_dir, FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for k in KEYS:
            if k in cur:
                w.writerow([k, cur[k], day])
    os.replace(tmp, os.path.join(input_dir, FILE))
    return len(values)
