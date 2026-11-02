# superpowers 스킬 벤더링

- 출처: obra/superpowers (superpowers-marketplace), 버전 6.3.0, 커밋 b36e0829c6d0140e93cfef2ca599b1b07d4a7797
- 이유: 클라우드 세션(claude.ai/code)은 `~/.claude` 플러그인이 세션마다 초기화되어 `.claude/settings.json`의 enabledPlugins가 로드되지 않았다. `.claude/skills/`는 클론에 포함되므로 skills/* 만 복사해 커밋한다.
- 범위: 플러그인의 `skills/*` 14개만. hooks·commands·tests는 제외.
- 이름: 플러그인일 때의 `superpowers:brainstorming` 대신 `brainstorming` 처럼 접두어 없이 등록된다.
- 갱신: 새 버전이 필요하면 같은 방법으로 덮어쓰고 이 파일의 버전·커밋을 고친다. 라이선스: `using-superpowers/LICENSE.superpowers`.
