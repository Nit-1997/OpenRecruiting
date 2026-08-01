import { v2Client } from '@/lib/v2-client';

export type AssistantIntent = 'browse_roles' | 'intake_call' | 'out_of_scope';

// One recruiter-authed Sonnet classification. Fail-open to 'out_of_scope' so the
// composer always gives the user a path forward (the two routing chips).
export async function classifyAssistantIntent(text: string): Promise<AssistantIntent> {
  try {
    const res = await v2Client.post<{ intent: AssistantIntent }>('/api/v2/assistant/route', {
      text,
    });
    return res.intent;
  } catch {
    return 'out_of_scope';
  }
}
