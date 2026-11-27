// calc.py 145-200: 입력 확인 목록 복사, R 시작, 출금일(F12 안내 포함), 기간, 설정 숫자, present.
import type { Data } from "../model/data";
import { DEFAULT_SETTINGS } from "../model/data";
import type { IsoDate } from "../model/dates";
import { payFriday, periodOf } from "../model/dates";
import { fmtComma, pyG } from "../model/py";
import { Issues, settingNum } from "../model/util";
import type { Ctx, Kind, Obj } from "./ctx";
import { NUM_SETTINGS, SETTING_LABELS } from "./projects";

function fmtSetting(v: number): string {
  return Number.isInteger(v) ? fmtComma(v) : pyG(v);
}

export function head(d: Data, kind: Kind, asof: IsoDate, start: IsoDate | null, pick: unknown, payday: IsoDate | null): Ctx {
  const issues = new Issues();
  issues.items = [...d.issues.items];
  const in_missing = [...(d.in_missing ?? [])];
  const invs: Obj[] = in_missing.length ? [] : d.invoices.map((v) => ({ ...v }));
  const R: Obj = { kind, asof };
  R["payday"] = payday !== null && payday > asof ? payday : payFriday(asof);
  if (payday !== null && payday <= asof) {
    issues.add("출금일", "-", `넣은 출금일 ${payday}이 기준일 ${asof}과 같거나 앞이라 다음 금요일 ${R["payday"]}로 잡음`);
  }
  const [p0, p1] = periodOf(kind, asof, start);
  R["period"] = [p0, p1];
  R["settings"] = { ...d.settings };
  const sn: Obj = {}, sd: Obj = {};
  R["settings_num"] = sn;
  R["settings_default"] = sd;
  const has = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k);
  for (const key of NUM_SETTINGS) {
    const dflt = settingNum(DEFAULT_SETTINGS, key, null as unknown as number)[0];
    let value: number, reason: string | null;
    if (!has(d.settings_line, key)) {
      value = dflt;
      reason = "설정 비어 있음";
    } else {
      [value, reason] = settingNum(d.settings, key, dflt);
    }
    if (key === "첫화면_프로젝트_표시수" && reason === null && (!Number.isInteger(value) || value < 0)) {
      value = dflt;
      reason = "0 이상 정수 아님";
    }
    const raw = has(d.settings, key) ? d.settings[key] : undefined;
    const line = has(d.settings_line, key) ? d.settings_line[key]! : "-";
    if (key === "예산_원가율" && reason !== "설정 비어 있음") {
      if (reason === null && String(raw).includes("%")) value = value / 100.0;
      if (reason !== null || !(value > 0 && value <= 1)) {
        sn[key] = null;
        issues.add("설정.csv", line,
          `예산_원가율 값 오류: '${raw === undefined ? "None" : raw}' (0 초과 1 이하 숫자, 예: 0.70) → 모든 프로젝트 원가 예산 계산 안 함`);
        continue;
      }
      sn[key] = value;
      continue;
    }
    if (reason !== null) {
      const label = SETTING_LABELS[key]!;
      const rawS = raw === undefined ? "None" : raw;
      const tail = `→ 기본값 ${fmtSetting(dflt)} 사용`;
      let msg: string;
      if (key === "예산_원가율") msg = "예산_원가율 설정 비어 있음 → 기본값 사용(0.70)";
      else if (reason === "설정 비어 있음") msg = `${label} 설정 비어 있음 ${tail}`;
      else if (reason === "숫자 아님") msg = `${label} 값이 숫자가 아님: '${rawS}' ${tail}`;
      else msg = `${label} 값은 0 이상 정수여야 함: '${rawS}' ${tail}`;
      sd[key] = reason;
      issues.add("설정.csv", line, msg);
    }
    sn[key] = value;
  }
  R["present"] = d.present;
  return {
    d, kind, asof, start, pick, payday, R, issues, checks: [],
    p0, p1, in_missing, invs,
    in_p: [], stale_accounts: [], proj: new Map(), plist: [], ar_rows: [], inv_proj: [],
    events: [], ym: "", year: "", pl_out: new Map(), leaked: {},
  };
}
