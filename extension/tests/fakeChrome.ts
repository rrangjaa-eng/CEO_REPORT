// 시험용 가짜 chrome (storage.local 은 메모리, onMessageExternal 은 등록된 듣개를 모아 둠)
type Listener = (msg: unknown, sender: chrome.runtime.MessageSender, reply: (r: unknown) => void) => boolean | void;

export function installFakeChrome(version = "1.0.0") {
  const store: Record<string, unknown> = {};
  const external: Listener[] = [];
  const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
  const fake = {
    storage: {local: {
      async get(keys: string | string[]) {
        const out: Record<string, unknown> = {};
        for (const k of Array.isArray(keys) ? keys : [keys]) if (k in store) out[k] = clone(store[k]);
        return out;
      },
      async set(items: Record<string, unknown>) { for (const [k, v] of Object.entries(items)) store[k] = clone(v); },
    }},
    runtime: {
      getManifest: () => ({version}),
      onMessageExternal: {addListener: (fn: Listener) => { external.push(fn); }},
    },
  };
  (globalThis as unknown as {chrome: unknown}).chrome = fake;
  return {store, external};
}
