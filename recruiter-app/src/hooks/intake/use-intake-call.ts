'use client';
import { useContext } from 'react';
import {
  type IntakeCallApi,
  IntakeCallContext,
} from '@/components/sub-agents/intake/IntakeCallProvider';

export function useIntakeCall(): IntakeCallApi {
  const ctx = useContext(IntakeCallContext);
  if (!ctx) throw new Error('useIntakeCall must be used inside <IntakeCallProvider>');
  return ctx;
}
