'use client';

import { useSubmitIntake } from '@/hooks/intake/use-submit-intake';
import type { IntakeSession } from '@/types/intake';
import { CoverageTable } from '../components/coverage-table';
import { LiveTranscript } from '../components/live-transcript';

interface Props {
  session: IntakeSession;
}

export function WrappingStage({ session }: Props) {
  // Centralized submit — shares the single in-flight guard with the canvas
  // auto-submit so the two paths can't double-fire one submit.
  const {
    submitting: isSubmitting,
    submittingError,
    submit: handleSubmit,
  } = useSubmitIntake(session);

  return (
    <div
      id="v2-intake-stage-wrapping"
      data-testid="v2-intake-stage-wrapping"
      className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-6"
    >
      <div className="space-y-4">
        <div
          id="v2-intake-stage-wrapping-banner"
          data-testid="v2-intake-stage-wrapping-banner"
          className="p-4 rounded-md text-sm"
          style={{
            background: 'var(--status-success-bg)',
            color: 'var(--status-success-fg)',
            border: '1px solid var(--status-success-bd)',
          }}
        >
          We've got what we need — review the coverage on the right and submit when you're ready.
        </div>
        <LiveTranscript turns={session.turns} />
      </div>
      <div className="space-y-4">
        <CoverageTable session={session} />
        {submittingError && (
          <p
            id="v2-intake-stage-wrapping-submit-error"
            role="alert"
            className="text-sm text-rose-400"
          >
            {submittingError}
          </p>
        )}
        <button
          id="v2-intake-stage-wrapping-submit-btn"
          data-testid="v2-intake-stage-wrapping-submit-btn"
          type="button"
          disabled={isSubmitting}
          onClick={() => void handleSubmit()}
          className="mz-btn-dark mz-btn-block"
        >
          {isSubmitting ? 'Submitting...' : 'Submit intake'}
        </button>
      </div>
    </div>
  );
}
