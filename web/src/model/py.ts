// 파이썬 흉내: 반올림·정수 나눗셈·글자 포맷·공백/숫자 판정이 파이썬과 같은 결과를 내게 한다.

/** 파이썬 round(x) (정수로): 0.5 는 짝수 쪽 (은행가 반올림). */
export function pyRound(x: number): number {
  if (!Number.isFinite(x)) return x;
  const f = Math.floor(x);
  const diff = x - f;
  if (diff < 0.5) return f;
  if (diff > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

/** 파이썬 int(x): 0 쪽 버림. */
export function pyInt(x: number): number {
  return Math.trunc(x);
}

/** 파이썬 a // b (내림). */
export function floorDiv(a: number, b: number): number {
  return Math.floor(a / b);
}

/** 파이썬 a % b (결과 부호는 b 와 같음). */
export function pyMod(a: number, b: number): number {
  const r = a % b;
  return r !== 0 && (r < 0) !== (b < 0) ? r + b : r;
}

function groupDigits(s: string): string {
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** 파이썬 "{:,}".format(n) — 정수 (소수면 int 로 자르지 않고 그대로 보여 주는 것은 pyFixed 사용). */
export function fmtComma(n: number): string {
  if (!Number.isInteger(n)) {
    // 파이썬 "{:,}".format(1234.5) = '1,234.5' (repr 기반)
    const neg = n < 0;
    const s = String(Math.abs(n));
    const [ip, fp] = s.split(".");
    return (neg ? "-" : "") + groupDigits(ip ?? "") + (fp !== undefined ? "." + fp : "");
  }
  const neg = n < 0;
  const s = BigInt(Math.abs(n)).toString();
  return (neg ? "-" : "") + groupDigits(s);
}

/** double 을 정확한 10진수로: [부호, 정수 BigInt digits, 소수 자릿수 scale] = |x| == digits / 10^scale. */
function exactDecimal(x: number): { neg: boolean; digits: bigint; scale: number } {
  const buf = new DataView(new ArrayBuffer(8));
  buf.setFloat64(0, x);
  const hi = buf.getUint32(0);
  const lo = buf.getUint32(4);
  const neg = (hi >>> 31) === 1;
  const exp = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let e: number;
  if (exp === 0) {
    e = -1074;
  } else {
    mant |= 1n << 52n;
    e = exp - 1075;
  }
  if (e >= 0) return { neg, digits: mant << BigInt(e), scale: 0 };
  const k = -e;
  return { neg, digits: mant * 5n ** BigInt(k), scale: k };
}

/** 파이썬 "{:.Nf}" (comma=true 면 "{:,.Nf}"): 정확한 값 기준 반올림, 정확히 반이면 짝수 쪽. */
export function pyFixed(x: number, n: number, comma = false): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  const { neg, digits, scale } = exactDecimal(x);
  let q: bigint;
  if (scale <= n) {
    q = digits * 10n ** BigInt(n - scale);
  } else {
    const div = 10n ** BigInt(scale - n);
    q = digits / div;
    const r = digits % div;
    const twice = r * 2n;
    if (twice > div || (twice === div && q % 2n === 1n)) q += 1n;
  }
  let s = q.toString();
  if (n > 0) {
    s = s.padStart(n + 1, "0");
    const ip = s.slice(0, s.length - n);
    s = (comma ? groupDigits(ip) : ip) + "." + s.slice(s.length - n);
  } else if (comma) {
    s = groupDigits(s);
  }
  return (neg ? "-" : "") + s;
}

// 파이썬 str.isspace() 와 같은 글자 (re 의 \s 도 같음)
export const PY_SPACE = "\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const SPACE_SET = new RegExp("[" + PY_SPACE + "]");
const STRIP_RE = new RegExp("^[" + PY_SPACE + "]+|[" + PY_SPACE + "]+$", "g");
const SPLIT_RE = new RegExp("[" + PY_SPACE + "]+");

export function pyIsSpaceChar(c: string): boolean {
  return SPACE_SET.test(c);
}

/** 파이썬 s.strip() (인자 없음). */
export function pyStrip(s: string): string {
  return s.replace(STRIP_RE, "");
}

/** 파이썬 s.split() (인자 없음). */
export function pySplit(s: string): string[] {
  return s.split(SPLIT_RE).filter((x) => x !== "");
}

/** 파이썬 "".join(s.split()) = 모든 공백 제거. */
export function pyRemoveSpace(s: string): string {
  return pySplit(s).join("");
}

// 파이썬 str.isdigit(): Nd + Numeric_Type=Digit (위첨자·원문자 등)
const DIGIT_RE = /^[\p{Nd}²³¹፩-፱᧚⁰⁴-⁹₀-₉①-⑨⑴-⑼⒈-⒐⓪⓵-⓽⓿❶-❾➀-➈➊-➒\u{10a40}-\u{10a43}\u{10e60}-\u{10e68}\u{11052}-\u{1105a}\u{1f100}-\u{1f10a}]+$/u;

export function pyIsDigit(s: string): boolean {
  return DIGIT_RE.test(s);
}

const ND = /^\p{Nd}$/u;

/** 유니코드 10진 숫자(Nd)를 ASCII 숫자로 (파이썬 int()·float() 가 받는 것과 같게). */
export function asciiDigits(s: string): string {
  if (/^[\x00-\x7f]*$/.test(s)) return s;
  let out = "";
  for (const ch of s) {
    if (ND.test(ch) && !(ch >= "0" && ch <= "9")) {
      let cp = ch.codePointAt(0)!;
      let k = 0;
      while (ND.test(String.fromCodePoint(cp - 1))) {
        cp -= 1;
        k += 1;
      }
      out += String(k % 10);
    } else {
      out += ch;
    }
  }
  return out;
}

/** 파이썬 int(s) (10진 정수 글자) — 못 읽으면 null. 앞뒤 공백·부호·밑줄 허용은 파이썬과 같게. */
export function pyIntParse(s: string): number | null {
  const t = asciiDigits(pyStrip(s));
  if (!/^[+-]?\d+(_\d+)*$/.test(t)) return null;
  return Number(t.replace(/_/g, ""));
}

/** 파이썬 float(s) — 못 읽으면 null. */
export function pyFloatParse(s: string): number | null {
  const t = asciiDigits(pyStrip(s)).toLowerCase();
  if (/^[+-]?(inf|infinity)$/.test(t)) return t.startsWith("-") ? -Infinity : Infinity;
  if (/^[+-]?nan$/.test(t)) return NaN;
  if (!/^[+-]?((\d+(_\d+)*)(\.(\d+(_\d+)*)?)?|\.\d+(_\d+)*)(e[+-]?\d+(_\d+)*)?$/.test(t)) return null;
  return Number(t.replace(/_/g, ""));
}

/** 파이썬 "%g" % v. */
export function pyG(v: number): string {
  if (Number.isNaN(v)) return "nan";
  if (!Number.isFinite(v)) return v > 0 ? "inf" : "-inf";
  if (v === 0) return Object.is(v, -0) ? "-0" : "0";
  const P = 6;
  const expStr = v.toExponential(P - 1);
  const exp = Number(expStr.split("e")[1]);
  if (exp < -4 || exp >= P) {
    let [m, e] = expStr.split("e") as [string, string];
    if (m.includes(".")) m = m.replace(/0+$/, "").replace(/\.$/, "");
    const en = Number(e);
    return m + "e" + (en < 0 ? "-" : "+") + String(Math.abs(en)).padStart(2, "0");
  }
  let s = pyFixed(v, Math.max(0, P - 1 - exp));
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s;
}

/** 안정 정렬 (Array.prototype.sort 는 ES2019 부터 안정). 파이썬 sorted(key=...) 와 같게: 키는 숫자·글자·배열. */
export type SortKey = number | string | boolean | null | SortKey[];

export function cmpKey(a: SortKey, b: SortKey): number {
  if (Array.isArray(a) && Array.isArray(b)) {
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i++) {
      const c = cmpKey(a[i] as SortKey, b[i] as SortKey);
      if (c !== 0) return c;
    }
    return a.length - b.length;
  }
  if (typeof a === "string" && typeof b === "string") return cmpStr(a, b);
  if (typeof a === "boolean" || typeof b === "boolean" || typeof a === "number" || typeof b === "number") {
    const x = Number(a), y = Number(b);
    return x < y ? -1 : x > y ? 1 : 0;
  }
  throw new TypeError("비교할 수 없는 키: " + String(a) + " / " + String(b));
}

/** 파이썬 글자 비교 (코드포인트 순). JS < 는 UTF-16 단위 순이라 보조 평면 글자에서 다르다. */
export function cmpStr(a: string, b: string): number {
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const x = a.codePointAt(i)!, y = b.codePointAt(i)!;
    if (x !== y) return x < y ? -1 : 1;
    if (x > 0xffff) i++;
  }
  return a.length - b.length;
}

export function sortedBy<T>(xs: readonly T[], key: (x: T) => SortKey, reverse = false): T[] {
  const idx = xs.map((x, i) => [key(x), i, x] as const);
  idx.sort((p, q) => {
    const c = cmpKey(p[0], q[0]);
    return c !== 0 ? (reverse ? -c : c) : p[1] - q[1];
  });
  return idx.map((p) => p[2]);
}
