import type {
  SourcingChannel,
  SourcingStrategyArtifactData,
  SourcingStrategyCandidate,
} from '@/components/artifacts/sourcing-strategy';

export const SOURCING_STRATEGY_ARTIFACT_ID = 'sourcing-strategy-v1';

export const SOURCING_STRATEGY_DEFAULTS: Omit<
  SourcingStrategyArtifactData,
  | 'strategyId'
  | 'version'
  | 'roleId'
  | 'roleTitle'
  | 'ownerName'
  | 'createdAtLabel'
  | 'trailSteps'
  | 'trailVisible'
  | 'channels'
  | 'candidates'
  | 'selectedCandidateIds'
  | 'userPreferences'
  | 'phase'
  | 'activeTab'
  | 'addedCount'
  | 'totalProfilesLabel'
  | 'savedToRole'
  | 'shareUrl'
> = {
  icp: 'Staff Product Manager with deep, hands-on ownership of AI/ML-powered products — a force-multiplier IC who can shape strategy at the company level without the overhead of people management.',
  location:
    'Sunnyvale, CA, USA — on-site / hybrid, mandatory (relocation acceptable if committed).',
  seniority: 'Staff PM (IC track — above Senior PM, below Group PM / Director).',
  experienceRequirements: [
    'Total experience: 6–10 years in product management.',
    'Max seniority: Staff PM / Principal PM — no Group PM, Director, or VP-level candidates.',
    'Startup experience strongly preferred — shipped products at recognizable US or global tech startups (e.g., Stripe, OpenAI, Anthropic, Loom, Figma, Notion, Scale AI, Brex) or high-growth Series B–D companies.',
  ],
  mustHaves: [
    'Deep, hands-on product ownership of AI/ML-powered products — not awareness, defined roadmap, drove adoption, measured outcomes on AI-native features.',
    'YC-backed startup experience (current or recent) OR demonstrated ownership in voice AI / conversational AI / speech tech / LLM-integrated product space.',
    'Strong cross-functional leadership — proven ability to align engineering, design, data science, and GTM without formal authority (hallmark of the Staff IC track).',
    'Located in or willing to relocate to Sunnyvale, CA — non-negotiable.',
  ],
  niceToHaves: [
    'Prior software engineering or ML engineering background before PM — highly valued at a startup where PMs go deep into technical trade-offs.',
    'ML/AI credentials — formal degree (CS/AI/ML), MS, or credible specialization (Stanford, Coursera Deep Learning, etc.).',
    'Experience with voice AI, speech recognition, NLP, dialogue systems, or real-time audio processing products.',
    'Track record of 0→1 product launches at early-stage startups (Seed–Series B).',
    'Experience navigating US regulatory or compliance contexts (SOC 2, HIPAA, CCPA).',
  ],
  targetCompanyTiers: [
    {
      tier: 'primary',
      label: 'Voice AI · Conversational AI · Speech tech',
      note: 'YC-backed or AI-native',
      companies: [
        'Observe.AI',
        'Bland AI',
        'Vapi',
        'Rime',
        'Deepgram',
        'AssemblyAI',
        'ElevenLabs',
        'Hume AI',
        'Play.ht',
        'Retell AI',
        'Cartesia AI',
      ],
    },
    {
      tier: 'secondary',
      label: 'Well-known US AI / tech startups',
      note: 'Series B–D, AI-native product surface',
      companies: [
        'Scale AI',
        'Cohere',
        'Mistral',
        'Perplexity',
        'Glean',
        'Hebbia',
        'Writer',
        'Harvey AI',
        'Orby AI',
      ],
    },
    {
      tier: 'tertiary',
      label: 'High-growth product-led startups',
      note: 'AI-PM experience exists within the product surface',
      companies: [
        'Notion',
        'Linear',
        'Loom (Atlassian)',
        'Figma',
        'Superhuman',
        'Brex',
        'Rippling',
        'Ramp',
      ],
    },
  ],
  redFlags: [
    'Pure consulting / strategy / business-analyst background with no real PM ownership.',
    'Zero AI/ML product experience — candidates who list AI as a bullet with no shipped output.',
    'Outside the Bay Area / Sunnyvale with no stated relocation intent.',
    'Over 12 years of experience — likely overqualified for the Staff IC level at a startup.',
    'Experience entirely at large enterprises (FAANG / BigTech) with no startup exposure — may struggle with startup ambiguity and resource constraints.',
  ],
  calibrationNote:
    "A Staff PM at a startup differs from FAANG's Staff PM — expect someone who acts as a force multiplier, shapes product strategy at the company level, and is comfortable being the most senior PM on the team (or one of two). They should bring the judgment of a Director without the overhead of people management.",
  // Legacy fields — retained so the persistence payload in
  // saveSourcingStrategy still type-checks. No longer rendered in the
  // artifact; the new ICP brief fields above are the authored surface.
  targetCompanies:
    'Observe.AI, Bland AI, Vapi, Rime, Deepgram, AssemblyAI, ElevenLabs, Hume AI, Scale AI, Cohere, Perplexity, Glean, Writer, Harvey AI (+ adjacent voice-AI / YC-backed AI-native startups).',
  exclude:
    'Pure consulting or business-analyst backgrounds, candidates with no AI/ML product ownership, candidates outside the Bay Area without relocation intent, 12+ years of experience, BigTech-only profiles with no startup exposure.',
  outreachVoice: '',
  sequence: '',
};

export const SOURCING_STRATEGY_CHANNELS: SourcingChannel[] = [
  {
    id: 'linkedin',
    name: 'LinkedIn Recruiter',
    statValue: 2840,
    statLabel: 'scanned',
    note: '28 above threshold',
    totalTarget: 2840,
    scanned: 0,
    status: 'pending',
  },
  {
    id: 'greenhouse-pool',
    name: 'Greenhouse Talent Pool',
    statValue: 412,
    statLabel: 'rescored',
    note: '9 re-surfaced past candidates',
    totalTarget: 412,
    scanned: 0,
    status: 'pending',
  },
  {
    id: 'referrals',
    name: 'Referrals',
    statValue: 6,
    statLabel: 'warm',
    note: 'Intros via your network',
    totalTarget: 6,
    scanned: 0,
    status: 'pending',
  },
  {
    id: 'wellfound',
    name: 'Wellfound',
    statValue: 84,
    statLabel: 'active',
    note: '2 strong matches',
    totalTarget: 84,
    scanned: 0,
    status: 'pending',
  },
];

export const SOURCING_STRATEGY_CANDIDATES: SourcingStrategyCandidate[] = [
  {
    id: 'str-amara',
    initials: 'AV',
    color: '#D64B1A',
    name: 'Amara Valeri',
    title: 'Sr. Product Manager',
    company: 'Lattice',
    location: 'San Francisco, CA',
    yearsLabel: '7 yrs',
    experienceYears: 7,
    industry: 'PLG B2B',
    sourceChannel: 'linkedin',
    sourceLabel: 'LinkedIn Recruiter',
    highlights: [
      'Owned activation metric end-to-end at Figma',
      'Shipped onboarding redesign · 2.1x conversion lift',
      'Fluent in SQL + Mixpanel; runs her own experiments',
    ],
    tags: ['activation lead', 'PLG', 'ex-Figma'],
    score: 92,
    email: 'amara.valeri@example.com',
    rank: 1,
  },
  {
    id: 'str-dario',
    initials: 'DO',
    color: '#1E3A5F',
    name: 'Dario Okonkwo',
    title: 'Staff Product Manager',
    company: 'Retool',
    location: 'New York, NY',
    yearsLabel: '8 yrs',
    experienceYears: 8,
    industry: 'Developer tools',
    sourceChannel: 'linkedin',
    sourceLabel: 'LinkedIn Recruiter',
    highlights: [
      "Led onboarding for Vercel's self-serve motion",
      'Redesigned Retool trial → paid conversion',
      'Writes strong strategy docs',
    ],
    tags: ['onboarding redesign', 'PLG', 'ex-Vercel'],
    score: 88,
    email: 'dario.okonkwo@example.com',
    rank: 2,
  },
  {
    id: 'str-nia',
    initials: 'NP',
    color: '#2F5D3A',
    name: 'Nia Pettersen',
    title: 'Sr. Product Manager',
    company: 'Linear',
    location: 'Remote · EU',
    yearsLabel: '6 yrs',
    experienceYears: 6,
    industry: 'PLG SaaS',
    sourceChannel: 'greenhouse-pool',
    sourceLabel: 'Greenhouse talent pool',
    highlights: [
      '2.1x funnel lift at Notion',
      'Moved from IC → tech-lead PM',
      'Applied Q3; re-surfaced by Cortex',
    ],
    tags: ['funnel lift 2.1x', 'PLG', 'ex-Notion'],
    score: 85,
    email: 'nia.pettersen@example.com',
    rank: 3,
  },
  {
    id: 'str-kiran',
    initials: 'KR',
    color: '#111111',
    name: 'Kiran Raasch',
    title: 'Sr. Product Manager',
    company: 'Airbase',
    location: 'San Francisco, CA',
    yearsLabel: '7 yrs',
    experienceYears: 7,
    industry: 'Fintech · PLG',
    sourceChannel: 'wellfound',
    sourceLabel: 'Wellfound',
    highlights: [
      'Led self-serve motion at Segment',
      'Owned activation from signup to first workflow',
      'Actively looking',
    ],
    tags: ['self-serve motion', 'PLG', 'ex-Segment'],
    score: 82,
    email: 'kiran.raasch@example.com',
    rank: 4,
  },
  {
    id: 'str-marisol',
    initials: 'MH',
    color: '#8A3A6B',
    name: 'Marisol Hendrix',
    title: 'Sr. Product Manager',
    company: 'Mercury',
    location: 'Brooklyn, NY',
    yearsLabel: '5 yrs',
    experienceYears: 5,
    industry: 'Fintech · PLG',
    sourceChannel: 'referrals',
    sourceLabel: 'Warm referral · Jenna',
    highlights: [
      'Built onboarding at Coda',
      'Referred by Jenna (our Head of Product)',
      'Quant fluency; ex-engineer',
    ],
    tags: ['referral · jenna', 'PLG', 'ex-Coda'],
    score: 80,
    email: 'marisol.hendrix@example.com',
    rank: 5,
  },
];

export const SOURCING_STRATEGY_TOTAL_LABEL = '45 profiles cleared ICP';
