import '@/components/sub-agents/intake/intake-design.css';
import type { ReactNode } from 'react';
import { CallPausedBanner } from '@/components/sub-agents/intake/CallPausedBanner';
import { IntakeCallProvider } from '@/components/sub-agents/intake/IntakeCallProvider';

export default function IntakeLayout({ children }: { children: ReactNode }) {
  return (
    <IntakeCallProvider>
      <div id="intake-design-root" className="mz-intake-root" data-motion="on">
        <CallPausedBanner />
        {children}
      </div>
    </IntakeCallProvider>
  );
}
