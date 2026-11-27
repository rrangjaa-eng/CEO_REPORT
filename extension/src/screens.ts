// 자동으로 받는 위하고 화면 목록과, 화면마다 꼭 와야 하는 자료 응답(NEED). 0.9.6 background.js 와 같은 값.
import type {Got} from "./messages";

export interface AutoScreen { prefix: string; mod: string; code: string; name: string; years?: number[]; onOpen?: boolean; fill?: string; tab?: string; match?: string; close?: boolean }
export const AUTO_SCREENS: AutoScreen[] = [
  {prefix: "결산", mod: "account", code: "SACL0105", name: "재무상태표", years: [0, -1]},
  {prefix: "결산", mod: "account", code: "SACL0108", name: "이익잉여금처분계산서", years: [0, -1]},
  {prefix: "결산", mod: "account", code: "SAAS0107", name: "고정자산관리대장", years: [0]},
  {prefix: "인사", mod: "humanresource", code: "SWPM0108", name: "사원등록", years: [0], onOpen: true},
  {prefix: "인사", mod: "humanresource", code: "SWSA0105", name: "월별급상여수당지급현황", years: [0, -1]},
  // 사업·기타소득조회: 귀속년월(1~12월)과 소득자(코드도움에서 전체 체크)를 채워야 조회된다 (2026-11-13 실제 화면 확인)
  {prefix: "인사", mod: "humanresource", code: "SWBU0103", name: "사업소득조회", years: [0, -1], fill: "earners"},
  {prefix: "인사", mod: "humanresource", code: "SWET0107", name: "기타소득조회", years: [0, -1], fill: "earners"},
  // 소득자별 근로소득원천징수부: 사원마다 줄을 눌러 달별 소득세·지방소득세를 받는다 (세무: 연말정산 환급·추가 납부 예상)
  {prefix: "인사", mod: "humanresource", code: "SWYM0107", name: "소득자별근로소득원천징수부", years: [0, -1], fill: "rows"},
  // 연말정산현황: 작년 해로 열면 '계속근무자' 쪽이 정산년월(작년 1월~올해 2월)을 스스로 채워 조회한다 (2026-11-13 실제 화면 확인)
  {prefix: "연말정산", mod: "humanresource", code: "SWYM0102", name: "연말정산현황", years: [-1], tab: "계속근무자 연말정산현황"},
];

export const RECON_SCREENS: AutoScreen[] = [
  {prefix: "대조", mod: "account", code: "SACL0104", name: "합계잔액시산표"},   // 계정별 잔액 (분개장과 같은 때)
  {prefix: "대조", mod: "account", code: "SAFM0109", name: "차입금현황"},       // 대출 만기·상환 방식 (잔액은 장부를 씀)
  {prefix: "대조", mod: "account", code: "SAFM0107", name: "예적금현황"},       // 정기예금 만기 (계좌번호는 지움)
  {prefix: "대조", mod: "account", code: "SACL0106", name: "손익계산서"},       // 매출·판관비 합계
  {prefix: "대조", mod: "account", code: "SAAC0103", name: "홈택스매출계산서"},   // 홈택스에서 받은 매출 계산서 (장부 매출전표와 맞춤). 이름에 '전자세금계산서'를 넣지 않는다: 프로그램이 매입 계산서 파일로 잘못 알아봄
  // 0.9.1 (사용자 2026-11-15 카드 '설정 없이 되는 7개 다 넣기'): 조회만으로 받히는 화면. 현금예금잔액검토(SACL0103)는 금융거래처를 골라야 하고,
  // 부가가치세신고서(SAVF0101)는 [수집하기](위하고 자료를 새로 만듦)를 눌러야 하고, 임시전표(JYAA0101)는 응답이 읽을 수 있는 자료가 아니라서
  // 자동으로 받지 않는다 (읽기 전용, 2026-11-15 실제 화면)
  {prefix: "대조", mod: "account", code: "SAFM0108", name: "차입금스케줄", onOpen: true},    // 이자율·상환 시작일 (열면 바로 옴)
  {prefix: "대조", mod: "account", code: "SABM0109", name: "거래처별초기이월"},             // 올해 첫날로 넘어온 계정 잔액 (작년 말 장부와 맞춤)
  {prefix: "대조", mod: "account", code: "SAAC0110", name: "자료수집현황", onOpen: true, match: "/collectingdata/"},   // 은행·카드·홈택스 자료가 언제까지 들어왔나
  {prefix: "대조", mod: "account", code: "SAVF0119", name: "부가세예정고지"},               // 세무서가 고지한 부가세 (없으면 빈 목록)
  {prefix: "대조", mod: "humanresource", code: "SWTA0101", name: "원천세신고", tab: "신고리스트", close: true},   // 저장된 원천징수이행상황신고서 목록 (반기·매월, 소득세)
];

// P1-4 (2026-11-15): 화면마다 프로그램이 읽는 자료 응답 (프로그램 wehago_raw.NEED 와 같은 글 — 시험이 둘을 맞춰 봄).
// 이 응답이 오지 않고 조건 응답(미승인 전표 확인·init 등)이나 오류 응답만 오면 '받음'으로 치지 않고 저장하지 않는다.
export const NEED: Record<string, string> = {"SACL0105": "/sacl0105/main$", "SACL0108": "/sacl0108/plusforw$", "SAAS0107": "/allfixlist$", "SWPM0108": "/swpm0108/condition$", "SWSA0105": "/swsa0105/total$", "SWBU0103": "/swbu0103/tab1$", "SWET0107": "/swet0107/other/tab01$", "SWYM0107": "/emp/income$", "SWYM0102": "/swym0102$", "SACL0104": "/sacl0104/account$", "SAFM0109": "/safm0109$", "SAFM0107": "/safm0107/balance/statement$", "SACL0106": "/sacl0106/0", "SAAC0103": "/saac0103/jungsang$", "SAFM0108": "/safm0108/\\d+$", "SABM0109": "/sabm0109/bsflist", "SAAC0110": "/collectingdata/", "SAVF0119": "/savf0119/top$", "SWTA0101": "/swta0101/sglist$"};
// 오류 응답: status 400 이상, 또는 오류 글(error)과 status 를 함께 둔 것 (재무상태표 '/main' 의 error_str 칸은 정상에도 있음)
function isErrResp(d: unknown): boolean {
  if (!d || typeof d !== "object" || Array.isArray(d)) return false;
  const o = d as {status?: unknown; error?: unknown};
  return (typeof o.status === "number" && o.status >= 400) || (typeof o.error === "string" && o.error !== "" && "status" in o);
}
export function hasData(sc: {code?: string} | null | undefined, got: Got[] | null | undefined): boolean {
  const need = NEED[String((sc && sc.code) || "").toUpperCase()];
  const re = need ? new RegExp(need) : null;
  return (got || []).some((g) => !isErrResp(g.data) && (!re || re.test(String(g.path || "").replace(/\/+$/, "").toLowerCase())));
}

