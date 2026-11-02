#!/bin/bash
# 클라우드 세션(Claude Code on the web)에서 gstack을 팀 모드(전역 설치)로 설치한다.
# 클라우드는 세션마다 새 컨테이너라 ~/.claude/skills/gstack이 남지 않고, 공식 팀 모드
# 훅(gstack-team-init required)은 설치하지 않고 막기만 한다. 그래서 이 훅이 세션을 열 때
# 공식 설치 명령(README Step 1·2)을 대신 실행한다. ~/.claude/skills는 세션 시작 전에
# 이미 있으므로 Claude Code가 새 스킬을 같은 세션에서 바로 읽는다.
# 로컬 PC 세션은 건드리지 않고(각자 전역 설치 + gstack 자체 자동 업데이트), 어떤 실패
# 경로도 세션 자체를 막지 않는다(SessionStart 훅).

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

GSTACK_DIR="$HOME/.claude/skills/gstack"
DONE_MARKER="$GSTACK_DIR/.install-gstack-done"

# 멱등: setup까지 끝난 설치가 있으면(resume 등) 건너뛴다. 업데이트는 gstack 자체 훅이 맡는다.
# 표식이 없는 디렉터리는 중간에 끊긴 설치이므로 지우고 다시 받는다.
if [ -f "$DONE_MARKER" ]; then
  # Codex는 디자인 검토 스킬에서만 — 그 밖의 gstack 리뷰는 Codex를 건너뛴다(사용자 결정 2026-10-01).
  "$GSTACK_DIR/bin/gstack-config" set codex_reviews disabled >/dev/null 2>&1 || true
  echo "install-gstack: already installed ($(cat "$GSTACK_DIR/VERSION" 2>/dev/null)) — skipping"
  exit 0
fi
rm -rf "$GSTACK_DIR"

# 버전 고정(2026-09-27): 세션마다 다른 gstack으로 /review·/design-review가 돌지 않게 커밋을 못 박는다.
# 올릴 때는 이 SHA를 바꾸고 결과 차이를 페이즈 경계에서 한 번 본다. GitHub은 전체 SHA 지정 fetch를 허용한다.
GSTACK_PIN="${GSTACK_PIN:-01593aa67c94780528e8f5121e47362502410ced}"  # 1.91.2.0
if ! ( mkdir -p "$GSTACK_DIR" && cd "$GSTACK_DIR" && git init -q && git remote add origin https://github.com/garrytan/gstack.git \
       && timeout 120 git fetch -q --depth 1 origin "$GSTACK_PIN" && git checkout -q FETCH_HEAD ) >/dev/null 2>&1; then
  rm -rf "$GSTACK_DIR"
  echo "install-gstack: pinned fetch failed ($GSTACK_PIN) — gstack skills unavailable this session" >&2
  exit 0
fi

# Chromium은 받지 않는다(클라우드는 /opt/pw-browsers 사전 설치본을 쓴다).
if ! (cd "$GSTACK_DIR" && GSTACK_SKIP_PLAYWRIGHT=1 timeout 600 ./setup --team </dev/null >/dev/null 2>&1); then
  echo "install-gstack: ./setup --team failed — gstack skills may be incomplete this session" >&2
  exit 0
fi

# 팀 모드 setup이 켜는 세션 시작 자동 업그레이드를 끈다(고정 버전 유지).
"$GSTACK_DIR/bin/gstack-config" set auto_upgrade false >/dev/null 2>&1 || true
# Codex는 디자인 검토 스킬에서만 — 그 밖의 gstack 리뷰는 Codex를 건너뛴다(사용자 결정 2026-10-01).
"$GSTACK_DIR/bin/gstack-config" set codex_reviews disabled >/dev/null 2>&1 || true

touch "$DONE_MARKER"
echo "install-gstack: installed gstack $(cat "$GSTACK_DIR/VERSION" 2>/dev/null) (team mode)"
exit 0
