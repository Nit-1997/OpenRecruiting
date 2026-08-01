'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { useIntakeSession } from '@/hooks/intake/use-intake-session';
import { reprocessSession } from '@/lib/intake/api';
import { useIntakeStore } from '@/stores/intake-store';
import { ReprocessAlreadyRunningError } from '@/types/intake';

export function useProcessTillNow() {
  const [postInFlight, setPostInFlight] = useState(false);
  const sessionId = useIntakeStore((s) => s.sessionId);
  const processTillNowRunId = useIntakeStore((s) => s.processTillNowRunId);
  const { session } = useIntakeSession(sessionId);
  const prevStatusRef = useRef<string | undefined>(session?.process_status);

  const runReprocess = useCallback(async () => {
    const sid = useIntakeStore.getState().sessionId;
    if (!sid) return;

    setPostInFlight(true);
    useIntakeStore.setState({ reprocessError: null });
    try {
      const res = await reprocessSession(sid);
      useIntakeStore.setState({ processTillNowRunId: res.process_run_id });
    } catch (e) {
      if (e instanceof ReprocessAlreadyRunningError) {
        useIntakeStore.setState({
          reprocessError: { type: 'already_running', message: e.message },
        });
      } else {
        useIntakeStore.setState({
          reprocessError: {
            type: 'generic',
            message: e instanceof Error ? e.message : 'Reprocess failed',
          },
        });
      }
    } finally {
      setPostInFlight(false);
    }
  }, []);

  useEffect(() => {
    const prev = prevStatusRef.current;
    const curr = session?.process_status;
    prevStatusRef.current = curr;
    if (prev === curr) return;
    const { processTillNowRunId } = useIntakeStore.getState();
    if (!processTillNowRunId) return;

    if (prev === 'running' && curr === 'idle') {
      useIntakeStore.setState({
        diffPanelOpen: true,
        diffBaseAnswers: session?.current_answers ?? {},
      });
    } else if (curr === 'failed') {
      useIntakeStore.setState({
        reprocessError: {
          type: 'lambda_failed',
          message: session?.process_error ?? 'Reprocess Lambda failed.',
        },
        diffPanelOpen: false,
        processTillNowRunId: null,
      });
    }
  }, [session?.process_status, session?.current_answers, session?.process_error]);

  const dismissDiffPanel = useCallback(() => {
    useIntakeStore.setState({
      diffPanelOpen: false,
      diffBaseAnswers: null,
      processTillNowRunId: null,
    });
  }, []);

  const isReprocessing =
    postInFlight ||
    (session?.process_status === 'running' && !!processTillNowRunId);

  return { runReprocess, dismissDiffPanel, isReprocessing };
}
