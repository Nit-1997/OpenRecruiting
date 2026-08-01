import { renderHook, act, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';

import { useIntakeStore } from '@/stores/intake-store';
import { ModalityConflictError } from '@/lib/intake/api';
import { VoiceDrainFailedError } from '@/types/intake';
import * as api from '@/lib/intake/api';
import { useModalitySwitch } from './use-modality-switch';

mock.module('@/lib/intake/api', () => {
  const actual = require('@/lib/intake/api');
  return { ...actual, switchModality: mock() };
});

const switchModalityMock = (api as unknown as { switchModality: ReturnType<typeof mock> })
  .switchModality;

describe('useModalitySwitch', () => {
  beforeEach(() => {
    switchModalityMock.mockReset();
    useIntakeStore.setState({
      sessionId: 'abc',
      pendingModality: null,
      switchError: null,
      pendingTransition: null,
      voiceError: null,
      hasLiveWebRTC: false,
      error: null,
    });
  });

  afterEach(() => {
    switchModalityMock.mockReset();
  });

  it('sets pendingModality optimistically while in flight', async () => {
    switchModalityMock.mockImplementation(
      () =>
        new Promise((resolve) =>
          setTimeout(
            () => resolve({ active_modality: 'text', drained: { drained: true }, session: null }),
            20,
          ),
        ),
    );
    const { result } = renderHook(() => useModalitySwitch());
    act(() => {
      void result.current.switchTo('text');
    });
    expect(useIntakeStore.getState().pendingModality?.to).toBe('text');
    await waitFor(() => expect(switchModalityMock).toHaveBeenCalledTimes(1));
  });

  it('on 200 leaves pendingModality set; store useEffect clears it on row update', async () => {
    switchModalityMock.mockResolvedValue({
      active_modality: 'text',
      drained: { drained: true },
      session: null,
    });
    const { result } = renderHook(() => useModalitySwitch());
    await act(async () => {
      await result.current.switchTo('text');
    });
    expect(useIntakeStore.getState().pendingModality?.to).toBe('text');
    expect(useIntakeStore.getState().switchError).toBeNull();
  });

  it('on 409 rolls back pendingModality and sets switchError={type:"conflict"}', async () => {
    switchModalityMock.mockRejectedValue(
      new ModalityConflictError('voice', 'text', 'another mode is currently active'),
    );
    const { result } = renderHook(() => useModalitySwitch());
    await act(async () => {
      await result.current.switchTo('text');
    });
    expect(useIntakeStore.getState().pendingModality).toBeNull();
    expect(useIntakeStore.getState().switchError?.type).toBe('conflict');
    const err = useIntakeStore.getState().switchError as { type: 'conflict'; held: string };
    expect(err.held).toBe('voice');
  });

  it('on 502 rolls back pendingModality and sets switchError={type:"drain_failed"}', async () => {
    switchModalityMock.mockRejectedValue(
      new VoiceDrainFailedError('voice agent did not drain cleanly', 'timeout after 10.0s'),
    );
    const { result } = renderHook(() => useModalitySwitch());
    await act(async () => {
      await result.current.switchTo('text');
    });
    expect(useIntakeStore.getState().pendingModality).toBeNull();
    expect(useIntakeStore.getState().switchError?.type).toBe('drain_failed');
  });

  it('on generic error rolls back pendingModality and sets switchError={type:"generic"}', async () => {
    switchModalityMock.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useModalitySwitch());
    await act(async () => {
      await result.current.switchTo('text');
    });
    expect(useIntakeStore.getState().pendingModality).toBeNull();
    expect(useIntakeStore.getState().switchError?.type).toBe('generic');
    expect(useIntakeStore.getState().switchError?.message).toBe('boom');
  });

  it('does nothing when sessionId is null', async () => {
    useIntakeStore.setState({ sessionId: null });
    const { result } = renderHook(() => useModalitySwitch());
    await act(async () => {
      await result.current.switchTo('text');
    });
    expect(switchModalityMock).not.toHaveBeenCalled();
  });

  it('isSwitching reflects in-flight state per direction', async () => {
    let resolveFn: ((v: unknown) => void) | undefined;
    switchModalityMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFn = resolve;
        }),
    );
    const { result } = renderHook(() => useModalitySwitch());
    act(() => {
      void result.current.switchTo('text');
    });
    expect(result.current.isSwitching).toBe('text');
    act(() => {
      resolveFn?.({ active_modality: 'text', drained: { drained: true }, session: null });
    });
    await waitFor(() => expect(result.current.isSwitching).toBeNull());
  });

  it('clearSwitchError wipes the error', async () => {
    switchModalityMock.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useModalitySwitch());
    await act(async () => {
      await result.current.switchTo('text');
    });
    expect(useIntakeStore.getState().switchError).not.toBeNull();
    act(() => {
      result.current.clearSwitchError();
    });
    expect(useIntakeStore.getState().switchError).toBeNull();
  });
});
