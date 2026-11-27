// calc.py risks (경영관리용 위험 분석과 해결방안) + debts.py extend_checks.
import type { Obj } from "./ctx";
import { daysBetween, type IsoDate } from "../model/dates";
import { d2s, won } from "../model/util";
import { pyFixed, sortedBy } from "../model/py";
import { withVat } from "./projects";

export const EXTEND_CHECK_DAYS = 60;

function validDay(text: unknown): boolean {
  const t = String(text ?? "").trim();
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  if (!m) return false;
  const y = +m[1]!, mo = +m[2]!, d = +m[3]!;
  if (y < 1 || mo < 1 || mo > 12 || d < 1) return false;
  const dim = [31, (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0 ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return d <= dim[mo - 1]!;
}

/** debts.extend_checks: 매년 연장 예정 대출 중 만기 60일 안 또는 지난 것 */
export function extendChecks(D: Obj | null | undefined, asof: IsoDate): Obj[] {
  const out: Obj[] = [];
  for (const ln of ((D ?? {})["loans"] as Obj[] | null | undefined) ?? []) {
    if (!ln["yearly"] || !validDay(ln["due"])) continue;
    const due = String(ln["due"]).trim();
    const days = daysBetween(asof, due);
    if (days <= EXTEND_CHECK_DAYS) {
      out.push({ vendor: ln["vendor"] || ln["account"], vcode: ln["vcode"], balance: ln["balance"], due, days });
    }
  }
  return out;
}

export function risks(R: Obj): Obj[] {
  const sn = R["settings_num"] as Obj;
  const out: Obj[] = [];
  const add = (level: string, area: string, fact: string, action: string) => { out.push({ level, area, fact, action }); };
  const min_cash = sn["위험_최소보유현금"] as number;
  const ar_days = sn["위험_미수경과일"] as number;
  const ui_days = sn["위험_미발행경과일"] as number;
  const data_days = sn["위험_자료경과일"] as number;
  const over_pct = sn["위험_예산초과율"] as number;
  const s2 = R["s2"] as Obj;
  for (const [mode, label] of [["firm", "확정·정기 지출"], ["all", "확정+추정"]] as const) {
    const [low, low_d] = s2["min"][mode] as [number | null, IsoDate | null];
    if (low === null || low === undefined) continue;
    if (low < min_cash) {
      add(low < 0 ? "높음" : "중간", "자금",
        `${label} 기준 최저 계산 잔액 ${won(low)}원 (${d2s(low_d)}). 최소 보유 기준 ${won(min_cash)}원.`,
        `${d2s(low_d)} 이전 입금예정 건의 입금일 확인·앞당김 요청, 같은 기간 지급 중 조정 가능한 건의 지급일 협의, `
        + "필요 시 단기 자금(한도대출 등) 사전 확보.");
    }
  }
  for (const L of extendChecks(R["debts"], R["asof"])) {
    const days = L["days"] as number;
    const left = days >= 0 ? `${days}일 남음` : `${-days}일 지남`;
    add(days >= 0 ? "중간" : "높음", "자금",
      `대출 ${L["vendor"]} 만기 ${d2s(L["due"])} (${left}) — 매년 연장 예정이라 원금 ${won(L["balance"])}원을 갚을 돈으로 잡지 않음.`,
      "은행·보증기관에 연장되는지 확인하세요. 연장되면 입력 폴더 대출만기.csv 에 새 만기일과 근거(메모)를 넣고, "
      + "안 되면 원금 상환 일정을 자금계획서에 넣으세요.");
  }
  if ((s2["out_missing"] as string[]).length) {
    add("높음", "자료", "지급 자료를 읽지 못해 지급예정이 빠졌으므로 기간별 계산 잔액과 최저 잔액을 계산하지 않음: "
      + (s2["out_missing"] as string[]).join(", ") + ".",
      "입력 폴더에 해당 CSV를 양식(입력양식 폴더)의 머리글 그대로 'CSV UTF-8' 또는 'CSV'로 저장.");
  }
  if ((s2["in_missing"] as string[]).length) {
    add("중간", "자료", "계산서 자료를 읽지 못해 발행 후 미수·발행금액·미발행금액과 계산서 입금예정을 알 수 없음: "
      + (s2["in_missing"] as string[]).join(", ") + ". "
      + "기간별 계산 잔액과 최저 잔액은 계산서 입금 없이 계산함 (실제보다 낮을 수 있음).",
      "입력 폴더에 계산서.csv를 양식(입력양식 폴더)의 머리글 그대로 'CSV UTF-8' 또는 'CSV'로 저장.");
  }
  if (R["s1"]["total"] === null || R["s1"]["total"] === undefined) {
    add("중간", "자료", "현재 계좌 잔액을 확인할 수 없어 기간별 계산 잔액과 최저 잔액을 계산하지 않음.",
      "계좌잔액.csv에 보고 기준일 잔액을 입력.");
  }
  if (s2["undated_out_n"]) {
    add("중간", "자금", `지급일이 없는 지급예정 ${s2["undated_out"] === null ? "금액 미확인" : won(s2["undated_out"]) + "원"} (`
      + `${s2["undated_out_n"]}건${s2["undated_out_unknown"] ? `, 금액 미확인 ${s2["undated_out_unknown"]}건 포함` : ""})이 일정 그래프에 들어가지 않음.`,
      "담당자에게 지급일 확정을 요청하고, 확정 전까지는 가장 이른 날짜로 가정한 잔액도 함께 검토.");
  }
  if (s2["undated_in_n"]) {
    add("중간", "자금", `입금일이 없는 입금예정 ${s2["undated_in"] === null ? "금액 미확인" : won(s2["undated_in"]) + "원"} (`
      + `${s2["undated_in_n"]}건${s2["undated_in_unknown"] ? `, 금액 미확인 ${s2["undated_in_unknown"]}건 포함` : ""})이 일정에 들어가지 않음.`,
      "거래처와 입금일을 확정해 일정에 반영.");
  }
  for (const P of R["s3"]["projects"] as Obj[]) {
    const spent = (P["committed"] !== null && P["committed"] !== undefined ? P["committed"] : P["expected"]) as number;
    if (P["budget"] !== null && P["budget"] !== undefined && P["budget"] > 0 && (spent * 100.0) / P["budget"] > over_pct) {
      add("높음", "프로젝트", `${P["id"]} ${P["name"]}: 등록 지출(장부 전 지급요청 포함) ${won(spent)}원이 예산 ${won(P["budget"])}원의 `
        + `${pyFixed((spent * 100.0) / P["budget"], 1)}%.`,
        "남은 지급요청·집행계획 중 줄일 수 있는 항목 확인, 추가 범위는 고객과 변경계약 협의, 예산 수정 등록.");
    }
    if (P["profit_end"] !== null && P["profit_end"] !== undefined && P["profit_end"] < 0) {
      add("높음", "프로젝트", `${P["id"]} ${P["name"]}: 종료 시점 예상이익 ${won(P["profit_end"])}원.`,
        "원가 절감 가능 항목과 추가 청구 가능 범위 검토.");
    }
    if (P["unknown_cost"]) {
      add("중간", "프로젝트", `${P["id"]} ${P["name"]}: 금액 미확인 원가 ${P["unknown_cost"]}건 — 예상이익 판단 불가.`,
        "담당자에게 견적·발주 금액 확정을 요청.");
    }
  }
  const s7 = R["s7"] as Obj;
  const nb = s7["no_budget"] as Obj[];
  if (nb.length) {
    add("중간", "프로젝트", `예산 미지정 프로젝트 ${nb.length}건, 예상총집행 ${won(s7["no_budget_expected"])}원.`,
      "인트라넷 사전 견적을 등록해 예산 대비 집행을 관리.");
  }
  for (const v of R["s5"]["overdue"] as Obj[]) {
    if (v["overdue_days"] >= ar_days) {
      add(v["overdue_days"] >= ar_days * 2 ? "높음" : "중간", "수금",
        `${v["project"]} ${v["client"]}: 입금예정일 ${d2s(v["due"])}에서 ${v["overdue_days"]}일 경과, 미수 ${won(v["outstanding"])}원.`,
        "거래처 담당자에게 지급 일정 확인, 필요 시 공문 발송.");
    }
  }
  for (const y of R["s5"]["event_unissued"]["rows"] as Obj[]) {
    if (y["days"] >= ui_days) {
      add("중간", "수금", `${y["P"]["id"]} ${y["P"]["name"]}: 행사 후 ${y["days"]}일, 미발행 ${won(y["unissued"])}원 `
        + `(받을 돈 ${won(withVat(y["unissued"]))}원, 부가세 포함).`,
        "발행 조건(검수·정산) 확인 후 계산서 발행.");
    }
  }
  if (s7["unlinked_txn_total"] || R["s3"]["unlinked_total"]) {
    add("중간", "자료", `프로젝트 미연결 지급 ${won(s7["unlinked_txn_total"])}원 (출금내역) / ${won(R["s3"]["unlinked_total"])}원 (집행자료).`,
      "지급마다 프로젝트번호를 연결해 프로젝트 원가에 반영.");
  }
  if (s7["unplanned_total"]) {
    add("중간", "지급 관리", `주간 지급계획에 없던 지급 ${won(s7["unplanned_total"])}원.`,
      "계획 외 지급의 승인 경로 확인, 다음 주 계획에 미리 등록.");
  }
  for (const a of s7["asof"] as Obj[]) {
    if (a["age"] === null || a["age"] > data_days) {
      add("중간", "자료", `${a["name"]} 기준일 ${d2s(a["date"])} (${a["age"] === null ? "날짜 없음" : `${a["age"]}일 전`}).`,
        "보고 전 해당 자료를 최신으로 갱신.");
    }
  }
  for (const x of s7["diffs"] as Obj[]) {
    if (x["state"] !== "확인완료") {
      add("중간", "자료", `${x["item"]}: ${x["a"]} ${won(x["a_amt"])}원 / ${x["b"]} ${won(x["b_amt"])}원.`,
        "두 자료를 건별로 대조해 차이 원인 확정.");
    }
  }
  for (const c of s7["checks"] as [string, number, number, boolean][]) {
    if (!c[3]) add("높음", "자료", `대조 불일치: ${c[0]} (${won(c[1])} / ${won(c[2])}).`, "입력 자료를 다시 확인.");
  }
  const order: Record<string, number> = { "높음": 0, "중간": 1 };
  return sortedBy(out, (r) => order[r["level"] as string] ?? 2);
}
