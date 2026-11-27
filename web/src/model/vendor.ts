// wehago.py norm_vendor·norm_code
import { PY_SPACE, pyIsDigit, pyRemoveSpace } from "./py";

const SPACES = new RegExp("[" + PY_SPACE + "]+", "g");

/** 거래처 이름 정규화: NFKC('㈜'→'(주)'), 공백 제거, '(주)'·'주식회사' 제거. */
export function normVendor(name: string | null | undefined): string {
  const s = (name || "").normalize("NFKC").replace(SPACES, "");
  return s.split("(주)").join("").split("주식회사").join("");
}

/** 거래처코드 정규화: 숫자 코드는 앞 0을 뗀다. */
export function normCode(code: string | number | null | undefined): string {
  const s = pyRemoveSpace(code === null || code === undefined || code === "" || code === 0 ? "" : String(code));
  return pyIsDigit(s) ? s.replace(/^0+/, "") || "0" : s;
}
