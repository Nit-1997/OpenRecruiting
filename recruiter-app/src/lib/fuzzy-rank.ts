// Dependency-free fuzzy ranking for short labels (role titles vs a meeting
// title). Deliberately tiny and pure — no fuzzy-search dependency, no React.
// Three single-purpose functions compose: tokenize → fuzzyScore → rankByFuzzy.

// Noise words common to calendar/meeting titles. Stripped from BOTH sides so a
// title like "Video Interview with Shipt (Staff AI Engineer)" reduces to the
// signal tokens {shipt, staff, ai, engineer} before scoring.
const STOPWORDS: ReadonlySet<string> = new Set([
  'a',
  'an',
  'and',
  'the',
  'for',
  'of',
  'to',
  'with',
  'vs',
  'interview',
  'interviews',
  'video',
  'call',
  'meeting',
  'sync',
  'chat',
  'screen',
  'screening',
  'phone',
  'onsite',
  'virtual',
  'intro',
  'introduction',
  'conversation',
  'discussion',
  'catch',
  'up',
  'debrief',
  'round',
  'final',
]);

/**
 * Lowercase, split on non-alphanumerics, drop stopwords and 1-char tokens.
 * Pure. "Staff AI Engineer!" → ["staff", "ai", "engineer"].
 */
export function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length >= 2 && !STOPWORDS.has(token));
}

/**
 * Score how well `target` matches `query`. Higher = better.
 *   exact token match  → 3
 *   substring (no token boundary) → 1
 * The score is the sum across the query's tokens, so a target that hits more
 * query tokens always outranks one that hits fewer. Returns 0 for no overlap.
 */
export function fuzzyScore(query: string, target: string): number {
  const queryTokens = tokenize(query);
  if (queryTokens.length === 0) return 0;
  const targetTokens = new Set(tokenize(target));
  const targetLower = target.toLowerCase();

  let score = 0;
  for (const token of queryTokens) {
    if (targetTokens.has(token)) {
      score += 3;
    } else if (targetLower.includes(token)) {
      score += 1;
    }
  }
  return score;
}

/**
 * Return a new array of `items` sorted by descending fuzzy score against
 * `query`. The sort is STABLE, so callers pre-sort by their preferred
 * tiebreaker (e.g. newest-first) and items with equal scores keep that order.
 * `getText` extracts the text to match for each item.
 */
export function rankByFuzzy<T>(
  items: readonly T[],
  query: string,
  getText: (item: T) => string,
): T[] {
  return items
    .map((item, index) => ({ item, index, score: fuzzyScore(query, getText(item)) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.item);
}
