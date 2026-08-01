'use client';

import { useRouter } from 'next/navigation';
import type { JSX } from 'react';
import { useState } from 'react';
import { IntakeApiError, type PublishResponse, publishSession } from '@/lib/intake/api';
import { useIntakeStore } from '@/stores/intake-store';
import type { IntakeSession, InterviewPlan } from '@/types/intake';
import { InterviewPlanEditor } from '../components/interview-plan-editor';

interface Props {
  session: IntakeSession;
  onPublished: (response: PublishResponse) => void;
}

export function PlanEditing({ session, onPublished }: Props): JSX.Element {
  const router = useRouter();
  const setEditPlanSession = useIntakeStore((s) => s.setEditPlanSession);
  const [isPublishing, setIsPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const plan = session.interview_plan;
  if (!plan) {
    return (
      <p id="intake-stage-plan-editing-loading" className="p-6 text-sm text-[var(--text-muted)]">
        Loading plan…
      </p>
    );
  }

  async function handlePublish(edited: InterviewPlan): Promise<void> {
    setError(null);
    setIsPublishing(true);
    try {
      const resp = await publishSession(session.id, edited);
      setEditPlanSession(null);
      onPublished(resp);
    } catch (e) {
      const msg =
        e instanceof IntakeApiError ? e.detail : 'Could not publish. Try again in a moment.';
      setError(msg);
    } finally {
      setIsPublishing(false);
    }
  }

  const handleBack = (): void => {
    setEditPlanSession(null);
    router.push('/intake');
  };

  return (
    <div
      id="intake-stage-plan-editing"
      className="fixed inset-0 z-[40] flex flex-col bg-[var(--bg)]"
    >
      <InterviewPlanEditor
        id="intake-plan-editor"
        session={session}
        initialPlan={plan}
        isPublishing={isPublishing}
        publishError={error}
        onPublish={handlePublish}
        onBack={handleBack}
      />
    </div>
  );
}
