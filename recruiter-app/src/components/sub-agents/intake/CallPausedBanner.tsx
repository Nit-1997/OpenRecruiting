'use client';

import { usePathname, useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { useIntakeCall } from '@/hooks/intake/use-intake-call';

export function CallPausedBanner() {
  const router = useRouter();
  const pathname = usePathname();
  const call = useIntakeCall();

  const onSessionRoute = pathname?.startsWith('/intake/sessions/');
  if (call.status !== 'paused' || !call.activeSessionId || onSessionRoute) return null;

  const resume = (): void => {
    router.push(`/intake/sessions/${call.activeSessionId}`);
  };

  return (
    <div
      id="intake-call-paused-banner"
      role="status"
      className="sticky top-0 z-40 flex items-center justify-between gap-3 bg-[var(--cortex-500)] px-4 py-2 text-[var(--bg)] shadow-sm"
    >
      <span className="truncate font-medium text-sm">
        {call.pausedSessionMeta?.role_name
          ? `Call paused for ${call.pausedSessionMeta.role_name}`
          : 'Call paused'}
      </span>
      <div className="flex shrink-0 items-center gap-2">
        <Button id="intake-call-paused-banner-resume" size="sm" onClick={resume}>
          Resume
        </Button>
        <Dialog>
          <DialogTrigger
            render={<Button id="intake-call-paused-banner-end" size="sm" variant="secondary" />}
          >
            End
          </DialogTrigger>
          <DialogContent showCloseButton={false}>
            <DialogTitle>End this call?</DialogTitle>
            <DialogDescription>
              Your conversation so far is saved. You can start a new one anytime.
            </DialogDescription>
            <div className="mt-4 flex justify-end gap-2">
              <DialogClose
                render={
                  <Button id="intake-call-paused-banner-cancel" variant="secondary" size="sm">
                    Cancel
                  </Button>
                }
              />
              <Button
                id="intake-call-paused-banner-end-confirm"
                variant="destructive"
                size="sm"
                onClick={() => call.end()}
              >
                End call
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}
