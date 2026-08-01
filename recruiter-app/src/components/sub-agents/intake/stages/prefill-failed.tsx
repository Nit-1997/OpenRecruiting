'use client';

interface Props {
  id: string;
  onContinue: () => void;
}

export function PrefillFailedStage({ id, onContinue }: Props) {
  return (
    <div id={id} className="mx-auto max-w-xl space-y-4 p-6">
      <div
        id={`${id}-banner`}
        role="alert"
        className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
      >
        We couldn't prefill from your context — you'll start fresh in the conversation.
      </div>
      <button
        id={`${id}-continue`}
        type="button"
        onClick={onContinue}
        className="rounded bg-[var(--cortex-500)] px-4 py-2 text-sm text-white hover:bg-[var(--cortex-600)]"
      >
        Continue anyway
      </button>
    </div>
  );
}
