import type { Round } from '@/domain';

export function isCustomRound(round: Pick<Round, 'is_custom' | 'for_candidate_id'>): boolean {
  return Boolean(round.is_custom || round.for_candidate_id);
}

export function getSharedRounds(rounds: Round[]): Round[] {
  return rounds.filter((r) => !isCustomRound(r));
}

export function getRoundsForCandidate(rounds: Round[], candidateId: string): Round[] {
  return rounds.filter(
    (r) => !isCustomRound(r) || r.for_candidate_id === candidateId,
  );
}
