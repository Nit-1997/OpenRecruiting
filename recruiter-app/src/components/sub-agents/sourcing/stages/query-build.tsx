'use client';

import { useSessionStore } from '@/stores';
import { cancelFreshQuery, submitQuery } from '../flow';
import { SourcingComposer } from '../sourcing-composer';

interface QueryBuildStageProps {
  id: string;
}

/**
 * Query build has no visible agent message — the greeting streams via
 * runSourcingStage('query_build') into session.messages, which TranscriptTail
 * renders above. This stage attaches the query composer + back affordance.
 */
export function QueryBuildStage({ id }: QueryBuildStageProps) {
  const session = useSessionStore((s) => s.sessions.sourcing);
  const initialValue =
    typeof session?.selections.queryText === 'string'
      ? (session.selections.queryText as string)
      : '';

  return (
    <div id={id} className="flex flex-col gap-6 pt-2">
      <SourcingComposer
        id={`${id}-composer`}
        initialValue={initialValue}
        onSubmit={(text) => {
          void submitQuery(text);
        }}
        onTryQuery={(text) => {
          void submitQuery(text);
        }}
      />
      <button
        id={`${id}-back`}
        type="button"
        onClick={cancelFreshQuery}
        className="inline-flex w-fit items-center gap-1.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em] hover:text-text-primary"
      >
        Back to mode choice
      </button>
    </div>
  );
}
