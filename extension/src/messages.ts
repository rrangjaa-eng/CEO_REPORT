// 화면(bridge)·배경·팝업 사이에 오가는 메시지 모양 (0.9.6 과 같은 모양, 타입만 붙임)

// 받은 응답 하나 (결산·인사 원본): 주소 경로와 (개인정보를 뺀) 응답. 원천징수부는 사원코드·줄 번호를 붙인다
export interface Got { path: string; data: unknown; cd_emp?: string; row?: number }

// bridge → 배경
export type Captured =
  | {type: "captured"; kind: string; params: Record<string, string>; columns: string[]; rows: unknown[][]; tot: unknown; company: string; screen: string}
  | {type: "planProgress"; date: string; rows: number}
  | {type: "planResult"; rows: unknown[][]; done: string[]; errors: string[]; company?: string}
  | {type: "closingCaptured"; path: string; data: unknown; screen: string; code: string};

// 배경 → bridge
export type BridgeRequest =
  | {type: "runScreen"; mod: string; code: string; onOpen: boolean; tab: string; match?: string; close?: boolean; fill?: string; sub?: string; year: number; ms: number}
  | {type: "clickQuery"}
  | {type: "armClosing"; ms: number}
  | {type: "collectPlan"; months: string[]};

export interface ScreenResult { ok: boolean; clicked?: boolean; dialog?: string; screen?: string; code?: string; got: Got[]; error?: string; v: number }
export interface ArmAck { ok: boolean; screen: string; code: string; v: number }

// 팝업·저장 창 → 배경
export type PopupRequest =
  | {type: "collectAll"; months: number}
  | {type: "collectBooks"}
  | {type: "collectRecon"}
  | {type: "collectNow"}
  | {type: "collectPlan"; months: number}
  | {type: "collectClosing"}
  | {type: "collectHr"}
  | {type: "collectYearEnd"}
  | {type: "openSaver"}
  | {type: "folderSaved"; names: string[]};

// 배경이 팝업에 주는 답 (받기 결과)
export interface CollectResult {
  error?: string;
  saved?: boolean;
  same?: boolean | number;   // 화면 여러 개를 받으면 '바뀐 것 없음' 개수
  file?: string;
  where?: string;
  screen?: string;
  done?: number;
  files?: {kind: string; file: string; same: boolean}[];
  parts?: Record<string, CollectResult>;
}
