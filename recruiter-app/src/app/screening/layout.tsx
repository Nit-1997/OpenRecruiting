import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ToastProvider } from '@/components/ui/toast';

// Public, no-login candidate screening portal. Lives outside the (shell) auth
// layout. ToastProvider is mounted here because it's otherwise only provided
// inside (shell). Never index these pages.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function ScreeningLayout({ children }: { children: ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}
