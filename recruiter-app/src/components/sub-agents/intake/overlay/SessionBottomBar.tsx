'use client';
import { MessageSquare, Mic, MicOff, PhoneOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { IconButton } from '@/components/ui/icon-button';
import type { IntakeModality } from '@/types/intake';

interface Props {
  modality: IntakeModality;
  isMuted?: boolean;
  onToggleMute?(): void;
  onHangup?(): void;
  onSwitch(to: IntakeModality): void;
  switching?: boolean;
}

export function SessionBottomBar({
  modality,
  isMuted,
  onToggleMute,
  onHangup,
  onSwitch,
  switching,
}: Props) {
  return (
    <footer
      id="intake-session-bottombar"
      className="sticky bottom-0 z-30 flex items-center justify-between gap-3 border-[var(--border)] border-t bg-[var(--surface)] px-4 py-3"
    >
      <div className="flex items-center gap-2">
        {modality === 'voice' && (
          <>
            <IconButton
              id="intake-session-mute"
              aria-label={isMuted ? 'Unmute' : 'Mute'}
              onClick={onToggleMute}
            >
              {isMuted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </IconButton>
            <Dialog>
              <DialogTrigger
                render={
                  <IconButton id="intake-session-hangup" aria-label="End call">
                    <PhoneOff className="h-4 w-4 text-red-600" />
                  </IconButton>
                }
              />
              <DialogContent showCloseButton={false}>
                <DialogTitle>End call?</DialogTitle>
                <DialogDescription>Your conversation so far is saved.</DialogDescription>
                <div className="mt-4 flex justify-end gap-2">
                  <DialogClose
                    render={
                      <Button id="intake-session-hangup-cancel" variant="secondary" size="sm">
                        Cancel
                      </Button>
                    }
                  />
                  <Button
                    id="intake-session-hangup-confirm"
                    variant="destructive"
                    size="sm"
                    onClick={onHangup}
                  >
                    End call
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </>
        )}
      </div>
      <Button
        id="intake-session-switch"
        variant="secondary"
        disabled={switching}
        onClick={() => onSwitch(modality === 'voice' ? 'text' : 'voice')}
      >
        {modality === 'voice' ? (
          <MessageSquare className="mr-2 h-4 w-4" />
        ) : (
          <Mic className="mr-2 h-4 w-4" />
        )}
        {switching ? 'Switching…' : modality === 'voice' ? 'Switch to chat' : 'Switch to voice'}
      </Button>
    </footer>
  );
}
