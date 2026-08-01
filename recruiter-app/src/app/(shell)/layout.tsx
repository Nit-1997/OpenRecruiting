import type { ReactNode } from 'react';
import { AppShell } from '@/components/shell/app-shell';
import { ToastProvider } from '@/components/ui/toast';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';

export default function ShellLayout({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <ConfirmDialogProvider>
        <AppShell id="app-shell">{children}</AppShell>
      </ConfirmDialogProvider>
    </ToastProvider>
  );
}
