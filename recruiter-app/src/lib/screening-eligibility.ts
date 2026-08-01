// Client-side mirror of the backend screening-eligibility heuristic
// (`backend/app/api/v2/services/plan_service.py` `_derive_screenable`).
// Used in the intake plan editor to decide whether to surface the
// "OpenRecruiting can take this round" nudge on a round BEFORE it exists in the DB.
//
// Keep this in lockstep with the backend rule — the two must agree so the
// editor never offers screening on a round publish would reject as ineligible.

// Screen-naming phrases. If the round name OR category (lowercased) contains
// one of these substrings, the round is a recruiter-style screen regardless of
// its position in the plan.
const SCREEN_NAME_KEYWORDS = [
  'recruiter screen',
  'recruiter call',
  'phone screen',
  'phone screening',
  'initial screen',
  'intro call',
  'screening',
] as const;

// The bare word "screen" only counts as its own token (so "Screenwriter Panel"
// does NOT match).
const SCREEN_WORD_RE = /\bscreen\b/;

// Categories whose name alone marks a screen.
const SCREEN_CATEGORIES = new Set(['screening', 'recruiter']);

// Conversational categories OpenRecruiting can run as a voice screen — but only when the
// round is the first one (round 2 of "behavioral" is a panel, not a screen).
const CONVERSATIONAL_CATEGORIES = new Set([
  'culture',
  'behavioral',
  'screening',
  'recruiter',
  'motivation',
]);

// Exercise categories that need live work a voice agent cannot run. These can
// never be a OpenRecruiting screen even when they sit at round 1.
const EXERCISE_CATEGORIES = new Set([
  'coding',
  'design',
  'system_design',
  'case',
  'domain',
  'take_home',
  'technical',
  'assessment',
]);

function isScreenByName(category: string, name: string): boolean {
  const haystack = `${name} ${category}`.trim();
  if (SCREEN_NAME_KEYWORDS.some((kw) => haystack.includes(kw))) return true;
  if (SCREEN_WORD_RE.test(haystack)) return true;
  return SCREEN_CATEGORIES.has(category);
}

/**
 * True when OpenRecruiting can host this round as a screening call.
 *
 * A round is screenable when:
 *   1. its name/category names a screen (recruiter/phone/initial screen, intro
 *      call, screening, or the bare word "screen" as a token); OR
 *   2. it is the FIRST round (roundIndex === 0) AND its category is
 *      conversational AND not an exercise category.
 *
 * `roundIndex` is the zero-based position in the plan.
 */
export function isRoundScreenable(
  name: string | null | undefined,
  category: string | null | undefined,
  roundIndex: number,
): boolean {
  const cat = (category ?? '').trim().toLowerCase();
  const nm = (name ?? '').trim().toLowerCase();

  if (isScreenByName(cat, nm)) return true;
  if (!cat) return false;

  return roundIndex === 0 && CONVERSATIONAL_CATEGORIES.has(cat) && !EXERCISE_CATEGORIES.has(cat);
}
