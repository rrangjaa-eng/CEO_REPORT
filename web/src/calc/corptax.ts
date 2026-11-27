// ceo_report/corptax.py depreciation (법인세 예상용 감가상각비).
import type { AccountRow } from "../model/data";
import { pyRound, pyInt } from "../model/py";

export const DEP_MODE = "prorate";

function depRows(accounts: AccountRow[] | null | undefined, year: string | number): AccountRow[] {
  return (accounts ?? []).filter((r) => r.ym.slice(0, 4) === String(year) && (r.name || "").includes("감가상각비"));
}

/** manual: 키 "연도" = 직접 입력, "대장|연도" = 고정자산대장. ledger 는 파이썬처럼 따로 받을 수 있음. */
export function depreciation(accounts: AccountRow[] | null | undefined, manual: Record<string, number>, ym: string,
                             mode: string | null = null, ledger: Record<string, number> | null = null): Record<string, unknown> {
  const md = mode || DEP_MODE;
  const year = ym.slice(0, 4), months = parseInt(ym.slice(5, 7), 10);
  const booked = depRows(accounts, year).filter((r) => r.ym <= ym).reduce((s, r) => s + (r.amount || 0), 0);
  const get = (o: Record<string, number> | null, k: string) => (o && Object.prototype.hasOwnProperty.call(o, k) ? o[k] ?? null : null);
  let annual: number | null, source: string;
  if (get(manual, year) !== null) {
    annual = get(manual, year); source = "직접 입력";
  } else if (get(ledger, year) !== null || get(manual, "대장|" + year) !== null) {
    annual = ledger && Object.prototype.hasOwnProperty.call(ledger, year) ? (ledger[year] ?? null) : get(manual, "대장|" + year);
    source = "고정자산대장";
  } else {
    const last = depRows(accounts, parseInt(year, 10) - 1);
    annual = last.length ? last.reduce((s, r) => s + (r.amount || 0), 0) : null;
    source = last.length ? "작년 장부" : "";
  }
  const share = md === "prorate" ? months : 12;
  const extra = annual === null ? null : Math.max(pyInt(pyRound((annual * share) / 12.0)) - booked, 0);
  return { annual, source, booked, extra, cur: null, months, mode: md };
}
