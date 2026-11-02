#!/bin/bash
# 클라우드 세션에서 eli5 스킬(/eli5 <주제>)을 쓸 수 있게 한다(사용자 승인 2026-10-06).
# 로컬 PC에는 플러그인 eli5@claude-community로 설치돼 있지만, 클라우드는 세션마다 새 컨테이너라
# 플러그인이 없고 프로젝트 enabledPlugins만으로는 설치되지 않았다(2026-10-06 headless 시험).
# 그래서 install-gstack.sh처럼 ~/.claude/skills에 스킬 파일을 직접 받는다. 로컬은 건드리지 않고,
# 어떤 실패도 세션을 막지 않는다(SessionStart 훅).

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

# 버전 고정: anthropics/claude-plugins-community의 eli5 1.0.0 커밋과 그 SKILL.md의 sha256.
# 스킬은 모든 세션 프롬프트에 들어가므로 해시가 다른 내용은 설치하지 않는다.
ELI5_PIN="f60f0454df3045f724c43c6346ec80bdcc3472b2"
ELI5_SHA256="3bb95cd13852051c5a1862e8b94da1de7cfba7415d418ab0ca4d762527d1b9a5"
URL="https://raw.githubusercontent.com/anthropics/claude-plugins-community/$ELI5_PIN/eli5/skills/eli5/SKILL.md"
SKILL_DIR="$HOME/.claude/skills/eli5"
SKILL_FILE="$SKILL_DIR/SKILL.md"

hash_ok() { echo "$ELI5_SHA256  $1" | sha256sum -c --status 2>/dev/null; }

# 멱등: 같은 해시의 파일이 있으면 건너뛴다. 다르거나 깨진 파일은 먼저 지우고 다시 받는다
# (다시 받기가 실패해도 검증 안 된 스킬이 남지 않게).
if [ -f "$SKILL_FILE" ] && hash_ok "$SKILL_FILE"; then
  echo "install-eli5: already installed — skipping"
  exit 0
fi
rm -f "$SKILL_FILE"

mkdir -p "$SKILL_DIR" && TMP="$(mktemp "$SKILL_DIR/.SKILL.md.XXXXXX")" \
  && curl -fsS -m 30 -o "$TMP" "$URL" && hash_ok "$TMP" && mv -f "$TMP" "$SKILL_FILE"
status=$?
[ -n "${TMP:-}" ] && rm -f "$TMP"
if [ "$status" -ne 0 ]; then
  echo "install-eli5: download, checksum or install failed ($ELI5_PIN) — eli5 unavailable this session" >&2
  exit 0
fi
echo "install-eli5: installed ($ELI5_PIN)"
exit 0
