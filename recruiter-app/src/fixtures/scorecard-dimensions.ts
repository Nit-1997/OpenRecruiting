export interface ScorecardDimension {
  id: string;
  title: string;
  description: string;
}

export const SCORECARD_DIMENSIONS: ScorecardDimension[] = [
  {
    id: 'prioritization',
    title: 'Prioritization',
    description:
      "Candidate's ability to remove and justify trade-offs across scope and constraints.",
  },
  {
    id: 'stakeholder',
    title: 'Stakeholder alignment',
    description:
      'Effectiveness in communicating and building agreement across different teams or functions.',
  },
  {
    id: 'ownership',
    title: 'Ownership',
    description:
      'Degree to which the candidate took personal responsibility for outcomes in past work.',
  },
  {
    id: 'systems',
    title: 'Cross-functional systems thinking',
    description: 'Reasoning about second-order effects across product, eng, and GTM.',
  },
];
