'use client';

import { useCallback, useState } from 'react';
import { switchModality as switchModalityApi, ModalityConflictError } from '@/lib/intake/api';
import { VoiceDrainFailedError } from '@/types/intake';
import { useIntakeStore } from '@/stores/intake-store';
import type { IntakeModality } from '@/types/intake';

const PENDING_MODALITY_EXPIRY_MS = 3_000;

export function useModalitySwitch() {
  const [isSwitching, setIsSwitching] = useState<IntakeModality | null>(null);

  const switchTo = useCallback(async (target: IntakeModality) => {
    const sessionId = useIntakeStore.getState().sessionId;
    if (!sessionId) return;

    setIsSwitching(target);
    useIntakeStore.setState({
      pendingModality: { to: target, expiresAt: Date.now() + PENDING_MODALITY_EXPIRY_MS },
      switchError: null,
    });

    try {
      await switchModalityApi(sessionId, target);
    } catch (e) {
      useIntakeStore.setState({ pendingModality: null });

      if (e instanceof ModalityConflictError) {
        useIntakeStore.setState({
          switchError: {
            type: 'conflict',
            held: e.held,
            requested: e.requested,
            message: e.detail,
          },
        });
      } else if (e instanceof VoiceDrainFailedError) {
        useIntakeStore.setState({
          switchError: {
            type: 'drain_failed',
            message: e.message,
            ...(e.innerError ? { innerError: e.innerError } : {}),
          },
        });
      } else {
        useIntakeStore.setState({
          switchError: {
            type: 'generic',
            message: e instanceof Error ? e.message : 'Switch failed',
          },
        });
      }
    } finally {
      setIsSwitching(null);
    }
  }, []);

  const clearSwitchError = useCallback(() => {
    useIntakeStore.setState({ switchError: null });
  }, []);

  return { switchTo, isSwitching, clearSwitchError };
}
