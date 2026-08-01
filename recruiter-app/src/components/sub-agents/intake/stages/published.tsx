import type { JSX } from 'react';
import type { IntakeSession } from '@/types/intake';

interface Props {
  session: IntakeSession;
  redirectUrl: string;
  onOpen: (url: string) => void;
}

export function Published({ session, redirectUrl, onOpen }: Props): JSX.Element {
  return (
    <div id="intake-stage-published" className="h-full flex flex-col items-center justify-center gap-6 text-slate-100 text-center px-6">
      <div>
        <p className="font-dm-mono text-xs uppercase tracking-widest text-emerald-400">Published</p>
        <h2 className="font-instrument-serif text-3xl mt-2">
          {session.form_data.role_name} is live.
        </h2>
        <p className="text-sm text-slate-400 mt-2 max-w-md">
          The interview plan is now attached to this role. You can edit it further from the role page.
        </p>
      </div>
      <button
        id="intake-stage-published-open"
        type="button"
        onClick={() => onOpen(redirectUrl)}
        className="px-5 py-2 rounded bg-cortex-600 text-slate-50 hover:bg-cortex-500"
      >
        Open in Roles -&gt;
      </button>
    </div>
  );
}
