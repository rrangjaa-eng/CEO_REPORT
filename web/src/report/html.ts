// 작은 HTML 글 만들기 도구 (틀 없음). 글자는 늘 escape 하고, 이미 만든 조각(Html)은 그대로 잇는다.
// 화면은 이 글을 한 번에 innerHTML 로 넣는다 — 스크립트·style 속성은 만들지 않는다 (CSP default-src 'self').
import { htmlEscape, maskRrn } from "../model/util";

export class Html {
  constructor(readonly s: string) {}
  toString(): string {
    return this.s;
  }
}

export type Child = Html | string | number | null | undefined | false | Child[];
export type Attrs = Record<string, string | number | boolean | null | undefined>;

/** 글자 칸: 주민번호 모양은 먼저 가리고(util.esc 와 같은 규칙) escape. */
export function esc(s: string): string {
  return htmlEscape(maskRrn(s));
}

export function raw(s: string): Html {
  return new Html(s);
}

function kids(c: Child, out: string[]): void {
  if (c === null || c === undefined || c === false) return;
  if (Array.isArray(c)) {
    for (const x of c) kids(x, out);
  } else if (c instanceof Html) {
    out.push(c.s);
  } else {
    out.push(esc(String(c)));
  }
}

export function cat(...children: Child[]): Html {
  const out: string[] = [];
  kids(children, out);
  return new Html(out.join(""));
}

const VOID = new Set(["br", "hr", "col"]);

/** h("td", {class: "n"}, "1,000") → <td class="n">1,000</td>. 속성 값 false·null 은 빼고 true 는 이름만. */
export function h(tag: string, attrs: Attrs | null, ...children: Child[]): Html {
  let a = "";
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false || v === "") continue;
    a += v === true ? ` ${k}` : ` ${k}="${esc(String(v))}"`;
  }
  if (VOID.has(tag)) return new Html(`<${tag}${a}>`);
  return new Html(`<${tag}${a}>${cat(...children).s}</${tag}>`);
}
