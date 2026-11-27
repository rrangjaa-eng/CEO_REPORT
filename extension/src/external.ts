// 1.0: 내 사이트(SITE_ORIGIN)에만 받은 자료를 넘긴다. 다른 사이트는 거절한다 (manifest externally_connectable 도 같은 주소만 허용).
import {SITE_ORIGIN} from "./config";
import {listDocs, type StoredDoc} from "./docs";

export type ExternalReply =
  | {ok: false; error: string}
  | {ok: true; version: string}
  | {ok: true; version: string; docs: StoredDoc[]};

export async function handleExternal(msg: unknown, sender: chrome.runtime.MessageSender): Promise<ExternalReply> {
  if (sender.origin !== SITE_ORIGIN) return {ok: false, error: "허용되지 않은 사이트"};
  const version = chrome.runtime.getManifest().version;
  const type = msg && typeof msg === "object" ? (msg as {type?: unknown}).type : undefined;
  if (type === "ping") return {ok: true, version};
  if (type === "list") return {ok: true, version, docs: await listDocs()};
  return {ok: false, error: "알 수 없는 요청"};
}

export function registerExternal(): void {
  chrome.runtime.onMessageExternal.addListener((msg, sender, reply) => {
    handleExternal(msg, sender).then(reply, (e: unknown) => reply({ok: false, error: String((e as Error)?.message ?? e)}));
    return true;
  });
}
