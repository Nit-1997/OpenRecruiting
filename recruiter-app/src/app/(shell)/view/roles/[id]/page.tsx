'use client';

import { use } from 'react';
import { RoleDetailPage } from '@/components/role-detail/role-detail-page';
import { useShellSync } from '@/hooks/use-shell-sync';

interface RoleDetailPageProps {
  params: Promise<{ id: string }>;
}

export default function Page({ params }: RoleDetailPageProps) {
  useShellSync();
  const { id } = use(params);
  return <RoleDetailPage id="role-detail" roleId={id} />;
}
