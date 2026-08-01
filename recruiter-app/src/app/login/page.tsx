'use client';

import { Loader2 } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect } from 'react';

// landing is the single login surface (shared `openrecruiting-auth` cookie). app-v2
// has no login screen of its own — bounce any direct hit on /login to landing,
// preserving the post-login redirect target.
function LoginRedirect() {
  const searchParams = useSearchParams();

  useEffect(() => {
    const landing = process.env.NEXT_PUBLIC_LANDING_URL || 'http://localhost:3000';
    const redirect = searchParams.get('redirect');
    const qs = redirect ? `?redirect=${encodeURIComponent(redirect)}` : '';
    window.location.href = `${landing}/login${qs}`;
  }, [searchParams]);

  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas">
      <Loader2 className="h-5 w-5 animate-spin text-text-secondary" />
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-dvh items-center justify-center bg-canvas">
          <Loader2 className="h-5 w-5 animate-spin text-text-secondary" />
        </main>
      }
    >
      <LoginRedirect />
    </Suspense>
  );
}
