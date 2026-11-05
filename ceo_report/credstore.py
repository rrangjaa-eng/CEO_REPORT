"""인트라넷 계정 기억 (사용자 2026-11-04).

외장하드의 입력 폴더 안 파일(입력/인트라넷계정.dat)에 둔다. 회사 PC·개인 PC 어디에 꽂아도 읽혀야 해서
PC에 묶이는 Windows 암호화(DPAPI·자격 증명 관리자)는 쓰지 않는다 (사용자 지시).
파일은 열어 봐도 글자가 바로 보이지 않게 가리기만 한다 — 진짜 잠금이 아니다. 외장하드를 잃어버리면 인트라넷 비밀번호를 바꾼다.
입력/ 폴더는 .gitignore 로 저장소에 올라가지 않는다.
"""
import base64
import json
import os

CRED_FILE = "인트라넷계정.dat"
_MAGIC = b"CEOR1"
_KEY = b"ceo-report-intranet-account/plant8"


def _mix(data):
    return bytes(b ^ _KEY[i % len(_KEY)] for i, b in enumerate(data))


def path_of(input_dir):
    return os.path.join(input_dir, CRED_FILE)


def save(input_dir, user_id, password):
    user_id, password = (user_id or "").strip(), password or ""
    if not user_id or not password:
        raise ValueError("ID와 비밀번호를 모두 넣어야 기억합니다")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    raw = json.dumps({"id": user_id, "pw": password}, ensure_ascii=False).encode("utf-8")
    body = _MAGIC + base64.b64encode(_mix(raw))
    tmp = path_of(input_dir) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path_of(input_dir))


def load(input_dir):
    """-> (ID, 비밀번호) 또는 None (없거나 읽을 수 없음)."""
    try:
        with open(path_of(input_dir), "rb") as f:
            body = f.read()
        if not body.startswith(_MAGIC):
            return None
        got = json.loads(_mix(base64.b64decode(body[len(_MAGIC):])).decode("utf-8"))
        uid, pw = str(got.get("id") or ""), str(got.get("pw") or "")
        return (uid, pw) if uid and pw else None
    except (OSError, ValueError, TypeError):
        return None


def clear(input_dir):
    """-> 지웠으면 True."""
    try:
        os.remove(path_of(input_dir))
        return True
    except FileNotFoundError:
        return False
