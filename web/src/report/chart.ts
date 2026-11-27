// 예상 잔액 그림 (선 그림, 한 축). 선 두 개: 확정·정기 지출 기준(강조색) · 예상 입출금까지 넣은 잔액(회색).
// 최소 보유현금은 가는 점선(기준선), 0원은 진한 가는 선. 점은 r=4 + 흰 테두리 2px, 최소 보유현금 밑이면 빨간 점.
// 숫자는 끝 점과 가장 낮은 점에만 (나머지는 아래 표와 점 위 title). 색은 표시일 뿐 — 범례·글자로도 구분된다.
import { esc, h, raw, type Html } from "./html";
import { won } from "./fmt";
import { pyRound } from "../model/py";

export interface BalPoint { label: string; firm: number | null; all: number | null }

const W = 400, PL = 40, PR = 62, PT = 16, PB = 28;

function niceStep(raw_: number): number {
  const mag = 10 ** Math.floor(Math.log10(raw_));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * mag >= raw_) return m * mag;
  return 10 * mag;
}

/** 세로축 금액: 억·만 단위로 짧게 (render._axis) */
export function axisText(v: number): string {
  if (v === 0) return "0";
  const sign = v < 0 ? "−" : "";
  const a = Math.abs(v);
  // 파이썬 round·'{:,.0f}' 처럼 .5 는 짝수 쪽으로
  if (a >= 100_000_000) return `${sign}${pyRound(a / 1_000_000) / 100}억`;
  if (a >= 10_000) return `${sign}${pyRound(a / 10_000).toLocaleString("en-US")}만`;
  return sign + a.toLocaleString("en-US");
}

/** 짧은 금액 (점 옆 글자): 1.2억 · 3,400만 */
function shortWon(v: number): string {
  return axisText(v);
}

export function balanceChart(pts: BalPoint[], minCash: number | null, H = 230): Html {
  const firm = pts.map((p) => p.firm).filter((v): v is number => v !== null);
  if (pts.length < 2 || !firm.length) return raw("");
  const all = pts.map((p) => p.all).filter((v): v is number => v !== null);
  const vals = [0, ...firm, ...all, ...(minCash !== null ? [minCash] : [])];
  const step = niceStep((Math.max(...vals) - Math.min(...vals)) / 4 || 1);
  let hi = step * Math.ceil(Math.max(...vals) / step);
  const lo = step * Math.floor(Math.min(...vals) / step);
  if (hi === lo) hi = lo + step;
  const y = (v: number) => PT + ((hi - v) * (H - PT - PB)) / (hi - lo);
  const gw = (W - PL - PR) / pts.length;
  const x = (i: number) => PL + i * gw + gw / 2;
  const f1 = (n: number) => n.toFixed(1);
  const out: string[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) {
    out.push(`<line class="grid" x1="${PL}" x2="${W - PR + 8}" y1="${f1(y(v))}" y2="${f1(y(v))}"/>`);
    out.push(`<text class="ax" x="${PL - 6}" y="${f1(y(v) + 4)}" text-anchor="end">${esc(axisText(v))}</text>`);
  }
  out.push(`<line class="zero" x1="${PL}" x2="${W - PR + 8}" y1="${f1(y(0))}" y2="${f1(y(0))}"/>`);
  if (minCash) {
    out.push(`<line class="floor" x1="${PL}" x2="${W - PR + 8}" y1="${f1(y(minCash))}" y2="${f1(y(minCash))}"/>`);
    out.push(`<text class="lab floor-t" x="${PL + 4}" y="${f1(y(minCash) - 4)}">최소 보유현금 ${esc(shortWon(minCash))}</text>`);
  }
  pts.forEach((p, i) => {
    out.push(`<text class="ax" x="${f1(x(i))}" y="${H - PB + 18}" text-anchor="middle">${esc(p.label)}</text>`);
  });
  const line = (key: "firm" | "all", cls: string) => {
    const xy = pts.map((p, i) => [i, p[key]] as const).filter((t): t is readonly [number, number] => t[1] !== null);
    if (xy.length < 2) return;
    out.push(`<polyline class="${cls}" points="${xy.map(([i, v]) => `${f1(x(i))},${f1(y(v))}`).join(" ")}"/>`);
  };
  line("all", "l-all");
  line("firm", "l-firm");
  // 점: 확정 기준 선에만. 최소 보유현금 밑이면 빨간 점
  let lowI = -1;
  pts.forEach((p, i) => {
    if (p.firm === null) return;
    if (lowI < 0 || p.firm < (pts[lowI]!.firm as number)) lowI = i;
    const low = minCash !== null && p.firm < minCash;
    out.push(`<circle class="${low ? "pt low" : "pt"}" cx="${f1(x(i))}" cy="${f1(y(p.firm))}" r="4"><title>${esc(
      `${p.label} 예상 잔액 ${won(p.firm)}원` + (p.all !== null ? ` · 예상 입출금까지 ${won(p.all)}원` : ""))}</title></circle>`);
  });
  // 끝 점 글자 (두 선), 가장 낮은 점 글자
  const last = pts.length - 1;
  const lf = pts[last]!.firm, la = pts[last]!.all;
  if (lf !== null) out.push(`<text class="lab end" x="${f1(x(last) + 8)}" y="${f1(y(lf) + 4)}">${esc(shortWon(lf))}</text>`);
  if (la !== null && la !== lf) {
    let ya = y(la) + 4;
    if (lf !== null && Math.abs(ya - (y(lf) + 4)) < 13) ya = y(lf) + 4 + (la < lf ? 13 : -13);
    out.push(`<text class="lab end sub" x="${f1(x(last) + 8)}" y="${f1(ya)}">${esc(shortWon(la))}</text>`);
  }
  if (lowI >= 0 && lowI !== last) {
    const v = pts[lowI]!.firm as number;
    out.push(`<text class="lab" x="${f1(x(lowI))}" y="${f1(y(v) + 18)}" text-anchor="middle">${esc(shortWon(v))}</text>`);
  }
  const svg = raw(`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc("기간별 예상 잔액")}">${out.join("")}</svg>`);
  const legend = h("div", { class: "legend" },
    h("span", null, h("i", { class: "k-firm" }), "예상 잔액 (확정분·정기 지출)"),
    all.length ? h("span", null, h("i", { class: "k-all" }), "예상 입출금까지 넣은 잔액") : null,
    minCash !== null ? h("span", null, h("i", { class: "k-floor" }), "최소 보유현금 (밑이면 빨간 점)") : null);
  return h("figure", { class: "chart" }, h("div", { class: "chart-box" }, svg), legend);
}
