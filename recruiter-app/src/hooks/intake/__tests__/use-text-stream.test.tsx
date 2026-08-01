import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, mock, beforeEach } from 'bun:test';
import { useTextStream } from '../use-text-stream';
import * as api from '@/lib/intake/api';

mock.module('@/lib/intake/api', () => {
  const actual = require('@/lib/intake/api');
  return {
    ...actual,
    streamTextTurn: mock(),
  };
});

const streamTextTurnMock = (api as any).streamTextTurn as ReturnType<typeof mock>;

beforeEach(() => {
  streamTextTurnMock.mockReset();
});

function asGen<T>(events: T[]) {
  async function* gen() {
    for (const e of events) yield e;
  }
  return gen();
}

describe('useTextStream', () => {
  it('starts idle and transitions streaming → idle on done', async () => {
    streamTextTurnMock.mockReturnValue(
      asGen([
        { type: 'text' as const, chunk: 'Hello ' },
        { type: 'text' as const, chunk: 'world.' },
        { type: 'done' as const, text: 'Hello world.', stop_reason: 'end_turn', user_turn_idx: 0, assistant_turn_idx: 1 },
      ]),
    );

    const { result } = renderHook(() => useTextStream('sess-1'));
    expect(result.current.status).toBe('idle');

    await act(async () => { await result.current.send('hi'); });

    await waitFor(() => expect(result.current.status).toBe('idle'));
    expect(result.current.streamingText).toBe('Hello world.');
    expect(result.current.lastDone?.assistant_turn_idx).toBe(1);
  });

  it('sets status=modality_conflict when streamTextTurn throws ModalityConflictError', async () => {
    streamTextTurnMock.mockImplementation(() => {
      throw new (api as any).ModalityConflictError('voice', 'text');
    });
    const { result } = renderHook(() => useTextStream('sess-1'));
    await act(async () => { await result.current.send('hi'); });
    expect(result.current.status).toBe('modality_conflict');
    expect(result.current.error?.code).toBe('modality_conflict');
  });

  it('surfaces in-stream error events into error state', async () => {
    streamTextTurnMock.mockReturnValue(
      asGen([{ type: 'error' as const, message: 'boom', code: 'internal_error' }]),
    );
    const { result } = renderHook(() => useTextStream('sess-1'));
    await act(async () => { await result.current.send('hi'); });
    expect(result.current.status).toBe('error');
    expect(result.current.error?.message).toBe('boom');
  });

  it('rejects send when streaming is already in flight (no-op, status stays streaming)', async () => {
    let resolveStream!: () => void;
    streamTextTurnMock.mockImplementation(() => {
      async function* gen() {
        await new Promise<void>(r => { resolveStream = r; });
        yield { type: 'done' as const, text: '', stop_reason: 'end_turn', user_turn_idx: 0, assistant_turn_idx: 1 };
      }
      return gen();
    });

    const { result } = renderHook(() => useTextStream('sess-1'));
    let firstP: Promise<void> | undefined;
    act(() => { firstP = result.current.send('first'); });
    await waitFor(() => expect(result.current.status).toBe('streaming'));
    await act(async () => { await result.current.send('second'); });
    expect(streamTextTurnMock).toHaveBeenCalledTimes(1);
    expect(streamTextTurnMock.mock.calls[0][1]).toBe('first');
    act(() => resolveStream());
    await act(async () => { await firstP; });
  });

  it('cancel() aborts in-flight stream', async () => {
    let abortObserved = false;
    streamTextTurnMock.mockImplementation((_id: any, _msg: any, signal: any) => {
      async function* gen() {
        await new Promise<void>((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            abortObserved = true;
            reject(new DOMException('aborted', 'AbortError'));
          });
        });
        yield { type: 'done' as const, text: '', stop_reason: null, user_turn_idx: 0, assistant_turn_idx: 1 };
      }
      return gen();
    });

    const { result } = renderHook(() => useTextStream('sess-1'));
    let sendP: Promise<void> | undefined;
    act(() => { sendP = result.current.send('hi'); });
    await waitFor(() => expect(result.current.status).toBe('streaming'));
    act(() => result.current.cancel());
    await act(async () => { await sendP; });
    expect(abortObserved).toBe(true);
    expect(result.current.status).toBe('idle');
  });

  it('unmounting the hook cancels the in-flight stream', async () => {
    let abortObserved = false;
    streamTextTurnMock.mockImplementation((_id: any, _msg: any, signal: any) => {
      async function* gen() {
        await new Promise<void>((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            abortObserved = true;
            reject(new DOMException('aborted', 'AbortError'));
          });
        });
        yield { type: 'done' as const, text: '', stop_reason: null, user_turn_idx: 0, assistant_turn_idx: 1 };
      }
      return gen();
    });

    const { result, unmount } = renderHook(() => useTextStream('sess-1'));
    let sendP: Promise<void> | undefined;
    act(() => { sendP = result.current.send('hi'); });
    await waitFor(() => expect(result.current.status).toBe('streaming'));
    unmount();
    await act(async () => { await sendP?.catch(() => undefined); });
    expect(abortObserved).toBe(true);
  });
});
