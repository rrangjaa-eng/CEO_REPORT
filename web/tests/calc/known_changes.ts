// golden/RULES.md '새 시스템에서 바꿀 것' 중 R 비교에 걸리는 것. 여기 적은 경로만 기대값 대신 want 로 비교한다.
// 각 항목은 그 결정을 단언하는 단위 시험도 따로 있어야 한다.
export interface KnownChange { case: string; kind: "weekly" | "monthly"; path: string; rule: string; want: unknown }
export const KNOWN_CHANGES: KnownChange[] = [];
