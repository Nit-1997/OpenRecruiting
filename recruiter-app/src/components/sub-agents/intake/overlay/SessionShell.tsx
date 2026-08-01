'use client';
import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';
import { useEffect } from 'react';

interface Props {
  topBar: ReactNode;
  body: ReactNode;
  bottomBar?: ReactNode;
}

export function SessionShell({ topBar, body, bottomBar }: Props) {
  const router = useRouter();
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') router.push('/intake');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [router]);

  return (
    <div id="intake-session-shell" className="fixed inset-0 z-[40] flex flex-col bg-[var(--bg)]">
      {topBar}
      <main className="flex flex-1 flex-col overflow-hidden">{body}</main>
      {bottomBar}
    </div>
  );
}
