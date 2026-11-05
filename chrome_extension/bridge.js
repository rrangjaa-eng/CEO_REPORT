// 화면에서 받은 응답을 필요한 칸만 남겨 확장 배경으로 넘기고, 배경의 '조회 눌러' 요청을 처리한다.
const KEEP = ["da_date", "no_acct", "nm_yuh", "nm_gubun_bungae", "cd_acctit", "nm_acctit", "mn_bungae1", "mn_bungae2",
  "nm_trade", "cd_trade", "nm_remark", "nm_project", "nm_dept", "nm_emp", "dt_insert", "sq_acttax2"];

window.addEventListener("message", (e) => {
  const m = e.data;
  if (e.source !== window || !m || m.__ceoReport !== 1) return;
  let j;
  try { j = JSON.parse(m.text); } catch (err) { return; }
  if (!j || !Array.isArray(j.data)) return;
  const rows = j.data.map((r) => KEEP.map((k) => (r[k] === undefined || r[k] === null ? "" : r[k])));
  const title = document.title || "";
  chrome.runtime.sendMessage({type: "captured", kind: m.kind, params: m.params, columns: KEEP, rows, tot: j.tot,
    company: (title.split(" - ")[1] || "").trim(), screen: title.split(" - ")[0]});
});

function findQueryButton() {
  const cands = [...document.querySelectorAll("button, a, span, div")].filter((el) =>
    el.offsetParent && el.children.length === 0 && (el.innerText || "").trim() === "조회");
  return cands.length ? (cands[0].closest("button") || cands[0]) : null;
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === "clickQuery") {
    const b = findQueryButton();
    if (b) b.click();
    reply({ok: !!b});
  }
});
