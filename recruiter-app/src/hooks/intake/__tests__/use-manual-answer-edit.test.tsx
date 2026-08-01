import { describe, it, expect, beforeEach, afterEach, mock } from 'bun:test';
import { renderHook, act } from '@testing-library/react';
import { useManualAnswerEdit } from '@/hooks/intake/use-manual-answer-edit';

const originalFetch = globalThis.fetch;

describe('useManualAnswerEdit', () => {
  afterEach(() => { globalThis.fetch = originalFetch; });

  it('saveEdit calls PATCH and resolves with applied[]', async () => {
    globalThis.fetch = mock(async () => new Response(JSON.stringify({ applied: ['q4_must_haves'] }), { status: 200 })) as typeof fetch;
    const { result } = renderHook(() => useManualAnswerEdit('sess-1'));
    let res: { applied: string[] } | null = null;
    await act(async () => {
      res = await result.current.saveEdit('q4_must_haves', { text: 'Python', status: 'validated' });
    });
    expect(res?.applied).toEqual(['q4_must_haves']);
    expect(result.current.savingQid).toBeNull();
  });

  it('savingQid is set during the patch and cleared after', async () => {
    let resolveFetch: (v: Response) => void = () => {};
    globalThis.fetch = mock(() => new Promise<Response>((res) => { resolveFetch = res; })) as typeof fetch;
    const { result } = renderHook(() => useManualAnswerEdit('sess-1'));
    const pending = act(async () => {
      void result.current.saveEdit('q1_role_overview', { text: 'payments' });
    });
    await new Promise((r) => setTimeout(r, 5));
    expect(result.current.savingQid).toBe('q1_role_overview');
    resolveFetch(new Response(JSON.stringify({ applied: ['q1_role_overview'] }), { status: 200 }));
    await pending;
    expect(result.current.savingQid).toBeNull();
  });

  it('surfaces error on 422 without throwing', async () => {
    globalThis.fetch = mock(async () => new Response(JSON.stringify({ detail: 'invalid status' }), { status: 422 })) as typeof fetch;
    const { result } = renderHook(() => useManualAnswerEdit('sess-1'));
    await act(async () => {
      await result.current.saveEdit('q1_role_overview', { status: 'invalid' as any });
    });
    expect(result.current.error).toContain('invalid status');
    expect(result.current.savingQid).toBeNull();
  });

  it('clearError nulls the error', async () => {
    globalThis.fetch = mock(async () => new Response(JSON.stringify({ detail: 'x' }), { status: 422 })) as typeof fetch;
    const { result } = renderHook(() => useManualAnswerEdit('sess-1'));
    await act(async () => { await result.current.saveEdit('q1_role_overview', { text: 'x' }); });
    act(() => { result.current.clearError(); });
    expect(result.current.error).toBeNull();
  });

  it('no-op when sessionId is null', async () => {
    const fetchMock = mock(async () => new Response('{}'));
    globalThis.fetch = fetchMock as typeof fetch;
    const { result } = renderHook(() => useManualAnswerEdit(null));
    await act(async () => { await result.current.saveEdit('q1_role_overview', { text: 'x' }); });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.error).toContain('no session');
  });
});
