// 확장 만들기: src 의 입구 파일마다 하나의 js 로 묶고(esbuild, iife), manifest.json·html 을 dist/ 에 그대로 둔다.
import {build} from "esbuild";
import {copyFile, mkdir, rm} from "node:fs/promises";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "dist");
const ENTRIES = ["background", "hook", "bridge", "popup", "saver"];
const STATIC = ["manifest.json", "popup.html", "saver.html"];

await rm(out, {recursive: true, force: true});
await mkdir(out, {recursive: true});
await build({
  entryPoints: Object.fromEntries(ENTRIES.map((e) => [e, join(here, "src", `${e}.ts`)])),
  outdir: out,
  bundle: true,
  format: "iife",
  target: "chrome120",
  charset: "utf8",
  logLevel: "info",
});
for (const f of STATIC) await copyFile(join(here, f), join(out, f));
console.log(`dist: ${ENTRIES.map((e) => e + ".js").concat(STATIC).join(", ")}`);
