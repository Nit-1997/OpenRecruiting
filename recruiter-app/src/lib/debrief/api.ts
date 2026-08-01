// Typed REST layer for the debrief feature (spec §10, Phase 3 Task 3.1).
//
// Routes through the SHARED v2 base (`getV2ApiBase`, env `NEXT_PUBLIC_API_V2_URL`)
// + the SAME token resolver and 401-refresh hook the rest of the app uses
// (`resolveV2Token` / `runV2UnauthorizedHandler` from `@/lib/v2-client`). This
// is the exact pattern `lib/intake/api.ts` uses — calling `fetch` directly
// against the shared base, NOT the `v2Client` object — so the layer is immune
// to the process-wide `mock.module('@/lib/v2-client')` stubs that other test
// files install (those stub the `v2Client` object; the statically-bound token +
// 401 helpers are snapshotted in test-setup and survive). No hand-rolled base,
// no localhost fallback.
//
// This module is also the single place backend response shapes are mapped to
// the FE types the components consume. The §4 `DebriefPacketResponse` is
// field-identical to the FE `DebriefPacket`, so `getPacket` returns it verbatim
// (no remap). The picker DTOs are mapped to the existing `RoleFixture` /
// `CandidateFixture` shapes so the conversational pickers stay unchanged.

import type { CandidateFixture, CandidateStatus } from '@/fixtures/candidates';
import type { DebriefPacket, DebriefVerdict } from '@/fixtures/debrief-packets';
import type { RoleFixture } from '@/fixtures/roles';
import { getV2ApiBase } from '@/lib/env';
import { resolveV2Token, runV2UnauthorizedHandler } from '@/lib/v2-client';

// ---------------------------------------------------------------------------
// Backend DTOs (backend/app/models/debrief.py) — EXACT field shapes.
// ---------------------------------------------------------------------------

/** Eligibility tier from the candidate picker endpoint (spec §9.1). */
export type DebriefEligibility = 'ready' | 'awaiting_signal' | 'early_stage';

/** Backend `RolePickItem` — a role with >= 2 debrief-eligible candidates. */
export interface RolePickItem {
  requisition_id: string;
  role_title: string;
  eligible_candidate_count: number;
}

/** Backend `CandidateSignal` — per-candidate feedback signal (spec §7). */
export interface CandidatePickSignal {
  /** Total candidate_feedback rows across the candidate's rounds. */
  feedback_count: number;
  /** Of those, how many carry a non-null evidence_status (graded, not a bare note). */
  evidence_backed_count: number;
}

/** Backend `CandidatePickItem` — a candidate tagged with its eligibility tier
 *  and feedback signal. */
export interface CandidatePickItem {
  candidate_id: string;
  name: string;
  eligibility: DebriefEligibility;
  rounds_completed: number;
  rounds_total: number;
  /** Completed rounds carrying a rating — the rounds the debrief averages over.
   *  The picker requires all co-selected candidates to share this count (a fair
   *  comparison), mirroring the backend parity gate. */
  rated_round_count: number;
  signal?: CandidatePickSignal;
}

/** Status on the thin packet-list row (includes the backend-only states). */
export type PacketListStatus = 'generating' | 'fresh' | 'superseded' | 'failed';

/** Backend `GenerateDebriefResponse` — immediate response to POST /generate. */
export interface GenerateDebriefResponse {
  packet_id: string;
  status: PacketListStatus;
}

/** Backend `PacketListItem` — a thin role-tab row (full body fetched on open). */
export interface PacketListItem {
  packet_id: string;
  status: PacketListStatus;
  candidate_ids: string[];
  verdict: DebriefVerdict | null;
  confidence: 'low' | 'medium' | 'high' | null;
  generated_at: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/** Thrown for any non-2xx debrief HTTP response. Carries the status so the
 *  poll loop can distinguish a 404 ("still generating") from a real failure. */
export class DebriefApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'DebriefApiError';
    this.status = status;
  }
}

export class DebriefGenerationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DebriefGenerationError';
  }
}

// ---------------------------------------------------------------------------
// Shared fetch (mirrors lib/intake/api.ts): shared base + token + 401-refresh.
// ---------------------------------------------------------------------------

function debriefUrl(path: string): string {
  return `${getV2ApiBase()}${path}`;
}

async function debriefFetch(
  path: string,
  init: Omit<RequestInit, 'headers'> & { headers: Record<string, string>; signal?: AbortSignal },
): Promise<Response> {
  const url = debriefUrl(path);
  const send = async (): Promise<Response> => {
    const token = await resolveV2Token();
    const headers: Record<string, string> = { ...init.headers };
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(url, { ...init, headers });
  };

  const res = await send();
  if (res.status !== 401) return res;
  // One shared 401-refresh + replay, exactly like the rest of the app.
  const refreshed = await runV2UnauthorizedHandler();
  if (!refreshed) return res;
  return send();
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let res: Response;
  try {
    res = await debriefFetch(path, {
      method,
      headers,
      credentials: 'include',
      cache: 'no-store',
      ...(signal ? { signal } : {}),
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch (e) {
    // A bounded-timeout abort surfaces as an AbortError — map it to a clear,
    // terminal DebriefApiError so the poll loop treats it as a real failure
    // (NOT a 404 "keep waiting") and routes to the failed stage.
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new DebriefApiError(0, 'Debrief request timed out.');
    }
    throw new DebriefApiError(0, (e as Error).message || 'Network error');
  }

  if (!res.ok) {
    let detail = `request failed (${res.status})`;
    try {
      const b = (await res.json()) as { detail?: unknown };
      if (typeof b.detail === 'string') detail = b.detail;
    } catch {
      // not JSON; keep the generic detail
    }
    throw new DebriefApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * Client-side ceiling for the generate/poll path. The backend `/generate` runs
 * the cortex skill inline and can block ~91.5s worst case (CortexDebriefClient
 * default: 3 attempts × 30s timeout + 1.5s linear backoff); without a bounded
 * client timeout the user would sit on the analyzing stage indefinitely on a
 * hung request. Kept comfortably above that worst case so a healthy-but-slow
 * call still lands — if CortexDebriefClient's timeout/retries grow, raise this.
 */
export const DEBRIEF_GENERATE_TIMEOUT_MS = 120_000;

/** Run a single `request` under a bounded AbortController timeout. On timeout
 *  the underlying fetch aborts → `request` throws `DebriefApiError(0, 'timed out')`. */
async function requestWithTimeout<T>(
  method: 'GET' | 'POST',
  path: string,
  body: unknown,
  timeoutMs: number,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await request<T>(method, path, body, controller.signal);
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Backend → FE mappers. The picker components consume fixture-shaped data;
// map at this layer so the components themselves stay store/fixture-agnostic.
// ---------------------------------------------------------------------------

const ELIGIBILITY_TO_STATUS: Record<DebriefEligibility, CandidateStatus> = {
  ready: 'ready',
  awaiting_signal: 'waiting',
  early_stage: 'early',
};

const ELIGIBILITY_FLAG: Record<DebriefEligibility, string> = {
  ready: 'Ready to debrief',
  awaiting_signal: 'Awaiting signal',
  early_stage: 'Early stage',
};

// Deterministic avatar palette (mirrors candidates.ts seeding order) so the
// real candidate cards get stable, legible avatar colors without a backend
// color field.
const AVATAR_COLORS = ['#EADFD4', '#D8EFE3', '#E9DFF5', '#FDE68A', '#BFDBFE', '#FECACA'];

function initialsFor(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

/** Map a `RolePickItem` to the `RoleFixture` shape `ReqPickGrid` renders. The
 *  grid only reads `id`/`title`/`loc`/`pipeline`/`status`/`dept`/`owner`; the
 *  rest are filled with neutral defaults so the card renders without fixtures. */
export function roleItemToFixture(item: RolePickItem): RoleFixture {
  const n = item.eligible_candidate_count;
  return {
    id: item.requisition_id,
    title: item.role_title,
    loc: '',
    pipeline: `${n} candidate${n === 1 ? '' : 's'} ready to debrief`,
    status: 'live',
    dept: '',
    owner: '',
    created_at: '',
    ready_to_debrief: true,
    must_have: [],
    nice_to_have: [],
  };
}

/** Map a `CandidatePickItem` to the `CandidateFixture` shape `CandidatePicker`
 *  renders. Avatar color/initials are derived deterministically. The canonical
 *  backend `eligibility` and feedback `signal` are carried through so the picker
 *  can gate selection on real signal and show "N scorecards · M evidence-backed". */
export function candidateItemToFixture(item: CandidatePickItem, index: number): CandidateFixture {
  return {
    id: item.candidate_id,
    name: item.name,
    role: '',
    stage: ELIGIBILITY_FLAG[item.eligibility],
    rounds: item.rounds_total,
    scoresIn: item.rounds_completed,
    avatar: initialsFor(item.name),
    color: AVATAR_COLORS[index % AVATAR_COLORS.length] ?? '#EADFD4',
    flag: `${item.rounds_completed}/${item.rounds_total} rounds`,
    status: ELIGIBILITY_TO_STATUS[item.eligibility],
    eligibility: item.eligibility,
    ratedRounds: item.rated_round_count,
    signal: {
      feedback_count: item.signal?.feedback_count ?? 0,
      evidence_backed_count: item.signal?.evidence_backed_count ?? 0,
    },
  };
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

/** GET /api/v2/debrief/roles → roles with >= 2 eligible candidates. */
export async function listRoles(): Promise<RolePickItem[]> {
  const out = await request<RolePickItem[]>('GET', '/api/v2/debrief/roles');
  return out ?? [];
}

/** GET /api/v2/debrief/roles/{requisition_id}/candidates → eligible candidates. */
export async function listCandidates(requisitionId: string): Promise<CandidatePickItem[]> {
  const out = await request<CandidatePickItem[]>(
    'GET',
    `/api/v2/debrief/roles/${requisitionId}/candidates`,
  );
  return out ?? [];
}

/** POST /api/v2/debrief/generate → create a packet (status 'generating').
 *  Bounded by `DEBRIEF_GENERATE_TIMEOUT_MS` so a hung backend can't strand the
 *  user on the analyzing stage. `timeoutMs` is injectable for tests. */
export async function generateDebrief(
  requisitionId: string,
  candidateIds: string[],
  timeoutMs: number = DEBRIEF_GENERATE_TIMEOUT_MS,
): Promise<GenerateDebriefResponse> {
  return requestWithTimeout<GenerateDebriefResponse>(
    'POST',
    '/api/v2/debrief/generate',
    { requisition_id: requisitionId, candidate_ids: candidateIds },
    timeoutMs,
  );
}

/** GET /api/v2/debrief/packets/{packet_id}. The backend 404s while generating
 *  or failed (→ `DebriefApiError(404)`, which the poll loop treats as "still
 *  generating"). A ready packet is returned verbatim — `DebriefPacketResponse`
 *  is field-identical to `DebriefPacket`. */
export async function getPacket(
  packetId: string,
  timeoutMs: number = DEBRIEF_GENERATE_TIMEOUT_MS,
): Promise<DebriefPacket> {
  return requestWithTimeout<DebriefPacket>(
    'GET',
    `/api/v2/debrief/packets/${packetId}`,
    undefined,
    timeoutMs,
  );
}

/** One persisted chat turn from the backend conversation store. `ts` is absent
 *  on turns persisted before server-side stamping shipped. */
export interface DebriefConversationTurn {
  role: 'user' | 'assistant' | string;
  text: string;
  idx: number | null;
  ts: string | null;
  proposed_action?: { kind: string; input: Record<string, unknown> } | null;
}

/** GET /api/v2/debrief/packets/{packet_id}/conversation → persisted chat turns,
 *  oldest first ([] when the packet has no conversation yet). Powers history
 *  hydration when reopening a packet whose chat happened on another
 *  device/session. */
export async function getConversation(packetId: string): Promise<DebriefConversationTurn[]> {
  const out = await request<{ turns: DebriefConversationTurn[] }>(
    'GET',
    `/api/v2/debrief/packets/${packetId}/conversation`,
  );
  return out?.turns ?? [];
}

/** GET /api/v2/debrief/roles/{requisition_id}/packets → thin list, newest first. */
export async function listPackets(requisitionId: string): Promise<PacketListItem[]> {
  const out = await request<PacketListItem[]>(
    'GET',
    `/api/v2/debrief/roles/${requisitionId}/packets`,
  );
  return out ?? [];
}

/**
 * POST /api/v2/debrief/packets/{packet_id}/save → commit a `draft` packet to
 * `fresh` (Phase 3 Task 3.1, spec §4.C5). The backend is idempotent when the
 * packet is already `fresh`, 404s a missing packet, and 409s a
 * generating/failed one — all surfaced as a `DebriefApiError` carrying the
 * status. Reuses the `GenerateDebriefResponse` `{packet_id, status}` shape.
 */
export async function saveDebrief(packetId: string): Promise<GenerateDebriefResponse> {
  return request<GenerateDebriefResponse>('POST', `/api/v2/debrief/packets/${packetId}/save`);
}

// ---------------------------------------------------------------------------
// Generate + poll orchestration
// ---------------------------------------------------------------------------

export interface PollOptions {
  /** Total attempts before timing out. Default 30 (~30s at 1s interval). */
  maxAttempts?: number;
  /** Delay between attempts in ms. Default 1000. */
  intervalMs?: number;
  /** Injectable sleep (tests pass a no-op). Default real setTimeout. */
  sleep?: (ms: number) => Promise<void>;
  /** Per-attempt `getPacket` abort timeout. Defaults to the generate ceiling. */
  getPacketTimeoutMs?: number;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Poll `getPacket(packetId)` until it resolves to a ready packet. While the
 * backend is still generating it 404s → `DebriefApiError(404)`, which we treat
 * as "keep waiting". Any other error (or a `status: 'failed'` body) is surfaced
 * as a `DebriefGenerationError`. Times out after `maxAttempts`.
 */
export async function pollPacket(packetId: string, opts: PollOptions = {}): Promise<DebriefPacket> {
  const maxAttempts = opts.maxAttempts ?? 30;
  const intervalMs = opts.intervalMs ?? 1000;
  const sleep = opts.sleep ?? defaultSleep;
  const getPacketTimeoutMs = opts.getPacketTimeoutMs ?? DEBRIEF_GENERATE_TIMEOUT_MS;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    let packet: DebriefPacket | undefined;
    try {
      packet = await getPacket(packetId, getPacketTimeoutMs);
    } catch (err) {
      // 404 = still generating (or failed-with-404); keep polling until timeout.
      if (err instanceof DebriefApiError && err.status === 404) {
        if (attempt < maxAttempts - 1) {
          await sleep(intervalMs);
          continue;
        }
        break;
      }
      // Any other error is terminal.
      throw new DebriefGenerationError(
        err instanceof Error ? err.message : 'Debrief generation failed.',
      );
    }
    if (packet) {
      // Defensive: a body that reports a terminal-failed status is an error.
      if ((packet as { status?: string }).status === 'failed') {
        throw new DebriefGenerationError('Debrief generation failed.');
      }
      return packet;
    }
    if (attempt < maxAttempts - 1) await sleep(intervalMs);
  }

  throw new DebriefGenerationError('Timed out waiting for the debrief packet.');
}
