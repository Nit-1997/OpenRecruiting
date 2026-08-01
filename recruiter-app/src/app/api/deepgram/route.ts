import { type NextRequest, NextResponse } from 'next/server';
import { getRecruiterUserFromRequest } from '@/lib/supabase-server';

// BFF that mints a short-lived Deepgram key for voice dictation. Two callers:
//  - the interviewer feedback portal (NOT logged in) — authorized by a
//    feedback-session token validated against the v2 backend;
//  - the recruiter app composer (logged in) — authorized by the shared
//    `openrecruiting-auth` session cookie.
// The Deepgram master key never leaves the server; the minted key lives 60s.

async function validateFeedbackSession(token: string): Promise<boolean> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!apiUrl) return false;
  try {
    const res = await fetch(`${apiUrl}/api/v2/public/feedback/validate-session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_token: token }),
      cache: 'no-store',
    });
    return res.ok;
  } catch {
    return false;
  }
}

async function mintTemporaryKey(comment: string): Promise<NextResponse> {
  const apiKey = process.env.DEEPGRAM_API_KEY;
  const projectId = process.env.DEEPGRAM_PROJECT_ID;
  if (!apiKey || !projectId) {
    return NextResponse.json({ error: 'Deepgram not configured' }, { status: 500 });
  }
  try {
    const response = await fetch(`https://api.deepgram.com/v1/projects/${projectId}/keys`, {
      method: 'POST',
      headers: {
        Authorization: `Token ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        comment,
        scopes: ['usage:write'],
        time_to_live_in_seconds: 60,
      }),
    });
    if (!response.ok) {
      return NextResponse.json({ error: 'Failed to create temporary key' }, { status: 500 });
    }
    const data = await response.json();
    return NextResponse.json({ apiKey: data.key });
  } catch {
    return NextResponse.json({ error: 'Failed to create temporary key' }, { status: 500 });
  }
}

export async function GET(request: NextRequest) {
  const feedbackSession = request.headers.get('x-feedback-session');

  // Public feedback portal: authorize by feedback-session token.
  if (feedbackSession) {
    const valid = await validateFeedbackSession(feedbackSession);
    if (!valid) {
      return NextResponse.json({ error: 'Invalid feedback session' }, { status: 401 });
    }
    return mintTemporaryKey(`temp_feedback_${Date.now()}`);
  }

  // Recruiter app: authorize by the shared openrecruiting-auth session cookie.
  const user = await getRecruiterUserFromRequest(request);
  if (!user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  return mintTemporaryKey(`temp_recruiter_${user.id}`);
}
