// 개발용 미리보기: golden 사례로 대표 보고 HTML 파일을 만든다 (서버 없이 브라우저로 열어 보기·인쇄 점검용).
// 제품 빌드(vite build)에는 들어가지 않는다 — index.html 이 이 파일을 부르지 않는다.
//   npx vite-node tests/report/preview.ts -- <출력 폴더> [사례,사례...]
import { listCases, loadCase } from "../calc/golden";
import { loadData } from "../../src/model/data";
import { buildReport } from "../../src/calc/report";
import { reportHtml } from "../../src/report/report";

interface NodeFs {
  readFileSync(p: string, enc: "utf8"): string;
  writeFileSync(p: string, s: string): void;
  mkdirSync(p: string, o: { recursive: boolean }): void;
}
declare const process: { getBuiltinModule(id: "node:fs"): NodeFs; argv: string[] };
const fs = process.getBuiltinModule("node:fs");

const args = process.argv.slice(2).filter((a) => a !== "--");
const out = (args[0] || "preview-out").replace(/\/?$/, "/");
const ids = args[1] ? args[1].split(",") : listCases();
const css = fs.readFileSync(decodeURIComponent(new URL("../../src/report/report.css", import.meta.url).pathname), "utf8");
fs.mkdirSync(out, { recursive: true });

for (const id of ids) {
  const c = loadCase(id);
  for (const kind of c.case.kinds) {
    const { R, stop } = buildReport(loadData(c.files), c.files, kind, c.case.asof, c.case.payday ?? null);
    const body = reportHtml(R, kind, { stop }).s;
    const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">`
      + `<title>${id} ${kind}</title><style>body{margin:0;background:var(--r-paper)}${css}</style></head><body>${body}</body></html>`;
    fs.writeFileSync(`${out}${id}_${kind}.html`, html);
    console.log(`${out}${id}_${kind}.html${stop.length ? " (막힘)" : ""}`);
  }
}
