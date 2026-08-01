import { describe, expect, mock, test } from 'bun:test';
import { render, waitFor } from '@testing-library/react';

mock.module('@/hooks/intake/use-intake-feature-flag', () => ({
  useIntakeFeatureFlag: () => ({ enabled: true, isLoading: false }),
}));

mock.module('@/components/sub-agents/intake/canvas', () => ({
  IntakeCanvas: ({ id, sessionId }: { id: string; sessionId: string | null }) => (
    <div id={id} data-session-id={sessionId ?? 'null'} />
  ),
}));

import SessionPage from './page';

describe('intake session deep-link page', () => {
  test('passes sessionId from params into IntakeCanvas', async () => {
    const params = Promise.resolve({ id: 'sess-xyz' });
    render(await SessionPage({ params }));
    await waitFor(() => {
      const canvas = document.getElementById('intake-session-page-canvas');
      expect(canvas?.dataset.sessionId).toBe('sess-xyz');
    });
  });
});
