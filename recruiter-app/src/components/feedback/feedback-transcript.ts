export type TranscriptTurn = { role: 'user' | 'bot'; text: string };

// The STT/LLM frequently mishears "OpenRecruiting" — normalize every spelling back.
const NAME_REGEX = /\bmayz[ue]?l[e]?\b/gi;

export function normalizeUserText(raw: string): string {
  return raw.replace(NAME_REGEX, 'OpenRecruiting').trim();
}

export function cleanBotText(raw: string): string {
  return raw
    .replace(/\[END\]/g, '')
    .replace(/\[interrupted[^\]]*\]/g, '')
    .replace(NAME_REGEX, 'OpenRecruiting')
    .trim();
}

export function appendUserTurn(turns: TranscriptTurn[], rawText: string): TranscriptTurn[] {
  const text = normalizeUserText(rawText);
  if (!text) return turns;
  return [...turns, { role: 'user', text }];
}

export function appendBotTurn(turns: TranscriptTurn[], rawInterim: string): TranscriptTurn[] {
  const text = cleanBotText(rawInterim);
  if (!text) return turns;
  const last = turns[turns.length - 1];
  if (last && last.role === 'bot' && last.text === text) return turns;
  return [...turns, { role: 'bot', text }];
}
