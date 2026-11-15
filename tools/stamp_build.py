"""exe 묶기 전에 판 표시(커밋·날짜)를 ceo_report/_build.py 에 쓴다 (2차 C16·P6-12, 2026-11-15).
GitHub Actions 에서 GITHUB_SHA 로, 없으면 git 으로 커밋을 읽는다. _build.py 는 저장소에 올리지 않는다(.gitignore)."""
import datetime as dt
import os
import subprocess

sha = os.environ.get("GITHUB_SHA", "")[:7]
if not sha:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short=7", "HEAD"]).decode().strip()
    except Exception:
        sha = "?"
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
text = "BUILD = %r\n" % ("%s %s" % (sha, dt.date.today().isoformat()))
with open(os.path.join(here, "ceo_report", "_build.py"), "w", encoding="utf-8") as f:
    f.write(text)
print(text.strip())
