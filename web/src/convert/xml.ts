// 작은 XML 읽기 (엑셀 부품용): 요소·속성·글자만. xml.etree.ElementTree 처럼 text(첫 자식 앞 글자)·tail 을 둔다.
// DOCTYPE·ENTITY 는 읽기 전에 막는다(xlsx.ts). 잘못된 모양이면 XmlError.

export class XmlError extends Error {}

export interface XEl {
  tag: string;            // 이름공간 접두어를 뗀 이름 (ET 의 '{ns}local' 에서 local 과 같음)
  rawTag: string;         // 접두어 포함 원래 이름
  attrs: Record<string, string>;   // 키는 원래 이름 (접두어 포함, 예: 'r:id')
  children: XEl[];
  text: string;
  tail: string;
}

const ENT: Record<string, string> = { lt: "<", gt: ">", amp: "&", quot: '"', apos: "'" };

function decodeEntities(s: string): string {
  if (!s.includes("&")) return s;
  return s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[A-Za-z]+);/g, (m, e: string) => {
    if (e[0] === "#") {
      const cp = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      if (!Number.isFinite(cp) || cp > 0x10ffff) throw new XmlError("잘못된 문자 참조");
      return String.fromCodePoint(cp);
    }
    const v = ENT[e];
    if (v === undefined) throw new XmlError("모르는 엔티티 " + m);
    return v;
  });
}

/** 바이트 → 글: BOM 으로 UTF-16 을 알아보고, 아니면 UTF-8. */
export function xmlText(b: Uint8Array): string {
  let enc = "utf-8";
  if (b[0] === 0xff && b[1] === 0xfe) enc = "utf-16le";
  else if (b[0] === 0xfe && b[1] === 0xff) enc = "utf-16be";
  else if (b[0] === 0x3c && b[1] === 0x00) enc = "utf-16le";
  else if (b[0] === 0x00 && b[1] === 0x3c) enc = "utf-16be";
  try {
    const t = new TextDecoder(enc, { fatal: true }).decode(b);
    return t.startsWith("﻿") ? t.slice(1) : t;
  } catch {
    throw new XmlError("글자 인코딩");
  }
}

const local = (name: string) => {
  const i = name.indexOf(":");
  return i < 0 ? name : name.slice(i + 1);
};

/** XML 글 → 뿌리 요소. */
export function parseXml(src: string): XEl {
  const s = src.replace(/\r\n?/g, "\n");   // XML 줄 끝 맞춤 (expat 과 같음)
  let i = 0;
  const n = s.length;
  const stack: XEl[] = [];
  let root: XEl | null = null;
  let last: XEl | null = null;   // 글자가 붙을 곳: 열린 요소의 text 또는 닫힌 형제의 tail
  let lastIsTail = false;
  const addText = (t: string) => {
    if (!t) return;
    if (!stack.length) {
      if (t.trim()) throw new XmlError("뿌리 밖 글자");
      return;
    }
    if (last && lastIsTail) last.tail += t;
    else (stack[stack.length - 1] as XEl).text += t;
  };
  while (i < n) {
    const lt = s.indexOf("<", i);
    if (lt < 0) { addText(decodeEntities(s.slice(i))); break; }
    if (lt > i) addText(decodeEntities(s.slice(i, lt)));
    if (s.startsWith("<!--", lt)) {
      const e = s.indexOf("-->", lt + 4);
      if (e < 0) throw new XmlError("주석이 닫히지 않음");
      i = e + 3;
      continue;
    }
    if (s.startsWith("<![CDATA[", lt)) {
      const e = s.indexOf("]]>", lt + 9);
      if (e < 0) throw new XmlError("CDATA 가 닫히지 않음");
      addText(s.slice(lt + 9, e));
      i = e + 3;
      continue;
    }
    if (s.startsWith("<?", lt)) {
      const e = s.indexOf("?>", lt + 2);
      if (e < 0) throw new XmlError("처리 지시가 닫히지 않음");
      i = e + 2;
      continue;
    }
    if (s.startsWith("<!", lt)) throw new XmlError("DOCTYPE 은 읽지 않음");
    if (s[lt + 1] === "/") {
      const e = s.indexOf(">", lt);
      if (e < 0) throw new XmlError("닫는 태그가 끊김");
      const name = s.slice(lt + 2, e).trim();
      const top = stack.pop();
      if (!top || top.rawTag !== name) throw new XmlError("태그 짝이 맞지 않음");
      last = top;
      lastIsTail = true;
      i = e + 1;
      continue;
    }
    // 여는 태그
    let j = lt + 1;
    const nameM = /^[^\s/>]+/.exec(s.slice(j, j + 200));
    if (!nameM) throw new XmlError("태그 이름 없음");
    const rawTag = nameM[0];
    j += rawTag.length;
    const attrs: Record<string, string> = {};
    for (;;) {
      while (j < n && /\s/.test(s[j] as string)) j++;
      if (j >= n) throw new XmlError("태그가 끊김");
      if (s[j] === ">" || (s[j] === "/" && s[j + 1] === ">")) break;
      const am = /^([^\s=/>]+)\s*=\s*("([^"]*)"|'([^']*)')/.exec(s.slice(j, j + 100000));
      if (!am) throw new XmlError("속성 모양이 틀림");
      const v = (am[3] ?? am[4] ?? "").replace(/[\t\n\r]/g, " ");
      if (v.includes("<")) throw new XmlError("속성 값에 <");
      if (Object.prototype.hasOwnProperty.call(attrs, am[1] as string)) throw new XmlError("속성이 두 번");
      attrs[am[1] as string] = decodeEntities(v);
      j += am[0].length;
    }
    const el: XEl = { tag: local(rawTag), rawTag, attrs, children: [], text: "", tail: "" };
    if (stack.length) (stack[stack.length - 1] as XEl).children.push(el);
    else if (root) throw new XmlError("뿌리가 둘");
    else root = el;
    if (s[j] === "/") {
      last = el;
      lastIsTail = true;
      i = j + 2;
    } else {
      stack.push(el);
      last = null;
      lastIsTail = false;
      i = j + 1;
    }
  }
  if (stack.length || !root) throw new XmlError("문서가 끝나지 않음");
  return root;
}

/** el.iter(): 자신과 모든 자손 (문서 순서). */
export function* iterEl(el: XEl): Generator<XEl> {
  yield el;
  for (const c of el.children) yield* iterEl(c);
}

/** 속성 값: 이름공간 접두어와 상관없이 local 이름으로 찾는다 (prefix 를 주면 그 접두어의 속성만). */
export function attr(el: XEl, name: string, nsLocalOnly = false): string | undefined {
  if (!nsLocalOnly && Object.prototype.hasOwnProperty.call(el.attrs, name)) return el.attrs[name];
  if (nsLocalOnly) {
    for (const [k, v] of Object.entries(el.attrs)) if (k.includes(":") && local(k) === name && !k.startsWith("xmlns")) return v;
  }
  return undefined;
}
