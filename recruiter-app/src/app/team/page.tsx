'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function TeamPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/?settings=team');
  }, [router]);
  return null;
}
