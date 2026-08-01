'use client';

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useRef,
  useState,
} from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export interface ConfirmOptions {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm action as destructive (red). */
  danger?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

/**
 * Imperative, promise-based confirm — the accessible replacement for
 * `window.confirm`. Backed by the shared {@link Dialog} (focus trap + restore,
 * ESC-to-cancel, role="dialog"/aria-modal via DialogContent).
 *
 *   const confirm = useConfirm();
 *   if (await confirm({ title: 'Delete role?', danger: true })) { ... }
 */
export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmContext);
  if (!confirm) {
    throw new Error('useConfirm must be used within a ConfirmDialogProvider');
  }
  return confirm;
}

interface PendingState {
  options: ConfirmOptions;
}

export function ConfirmDialogProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingState | null>(null);
  // Resolver for the in-flight confirm() promise. A ref (not state) so the
  // settle handlers always see the live resolver without re-renders.
  const resolverRef = useRef<((value: boolean) => void) | null>(null);

  const settle = useCallback((value: boolean) => {
    const resolve = resolverRef.current;
    resolverRef.current = null;
    setPending(null);
    resolve?.(value);
  }, []);

  const confirm = useCallback<ConfirmFn>((options) => {
    // If a confirm is somehow already open, resolve it false before replacing.
    resolverRef.current?.(false);
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
      setPending({ options });
    });
  }, []);

  const open = pending !== null;
  const options = pending?.options;
  const danger = options?.danger ?? false;

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog
        open={open}
        onOpenChange={(next) => {
          // Any close that isn't an explicit confirm (ESC, backdrop, X) is a
          // cancel and resolves false.
          if (!next && open) settle(false);
        }}
      >
        {options ? (
          <DialogContent data-slot="confirm-dialog">
            <DialogHeader>
              <DialogTitle>{options.title}</DialogTitle>
              {options.body ? (
                <DialogDescription>{options.body}</DialogDescription>
              ) : null}
            </DialogHeader>
            <DialogFooter>
              <Button
                id="confirm-dialog-cancel"
                variant="secondary"
                onClick={() => settle(false)}
              >
                {options.cancelLabel ?? 'Cancel'}
              </Button>
              <Button
                id="confirm-dialog-confirm"
                variant={danger ? 'destructive' : 'primary'}
                onClick={() => settle(true)}
              >
                {options.confirmLabel ?? 'Confirm'}
              </Button>
            </DialogFooter>
          </DialogContent>
        ) : null}
      </Dialog>
    </ConfirmContext.Provider>
  );
}
