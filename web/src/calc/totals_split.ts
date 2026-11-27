// 합계 나눠 보기 (새 값, 파이썬에 없음). 과대·과소 점검 2026-11-27.
// 기존 합계(R.s3.total.remain, R.s5.unissued, R.s4.unrecognized)는 프로젝트별 값을 그대로 더해서,
// 한 프로젝트의 음수(예산 초과, 계약보다 더 발행·반영)가 다른 프로젝트 몫을 깎고, 끝난 프로젝트의 안 쓸 예산이 잔여에 섞인다.
// 기존 값은 그대로 두고(정답 예시와 같음), 나눈 값을 따로 낸다: open − over (+ closed) = 기존 합계.
import type { Obj } from "./ctx";

type Split = { open: number; over: number; over_n: number };

function split(values: (number | null | undefined)[]): Split {
  const known = values.filter((v): v is number => v !== null && v !== undefined);
  const neg = known.filter((v) => v < 0);
  return { open: known.filter((v) => v > 0).reduce((s, v) => s + v, 0), over: -neg.reduce((s, v) => s + v, 0), over_n: neg.length };
}

export function totalsSplit(R: Obj): Obj {
  const plist = R["s3"]["projects"] as Obj[];
  const live = split(plist.filter((P) => !P["closed"]).map((P) => P["remain"]));
  const done = split(plist.filter((P) => P["closed"]).map((P) => P["remain"]));
  return {
    remain: { open: live.open, closed: done.open, over: live.over + done.over, over_n: live.over_n + done.over_n },
    unissued: split((R["s5"]["by_project"] as Obj[]).map((x) => x["unissued"])),
    unrecognized: split((R["s4"]["projects"] as Obj[]).map((P) => P["unrecognized"])),
  };
}
