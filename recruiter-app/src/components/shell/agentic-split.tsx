import type { ReactNode } from 'react';

interface AgenticSplitProps {
  id: string;
  chat: ReactNode;
  artifact: ReactNode;
}

/**
 * Split layout used inside a sub-agent canvas when an artifact wants to live
 * side-by-side with an ongoing agent chat. The outer ChatColumn already
 * provides full width minus the right rail, so this component fills that
 * space with a 0.8fr chat column + 1.2fr artifact column.
 */
export function AgenticSplit({ id, chat, artifact }: AgenticSplitProps) {
  return (
    <div
      id={id}
      className="-mx-12 grid min-h-[560px] flex-1 gap-0 border-border border-t"
      style={{ gridTemplateColumns: 'minmax(0, 0.8fr) minmax(0, 1.2fr)' }}
    >
      <section
        id={`${id}-chat`}
        aria-label="Agent chat"
        className="flex min-w-0 flex-col border-border border-r bg-bg px-8 py-6"
      >
        {chat}
      </section>
      <section
        id={`${id}-artifact`}
        aria-label="Comparative artifact"
        className="flex min-w-0 flex-col bg-white px-8 py-6"
      >
        {artifact}
      </section>
    </div>
  );
}
