/**
 * Scoped tests for CandidateProfilePanel.
 *
 * Contract: returns null for a falsy profile (non-ATS candidates render
 * nothing new) and for an "empty" profile object with no meaningful content;
 * renders the headline/summary/skills/links when populated.
 */

import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { CandidateProfile } from '@/domain/candidate';
import { CandidateProfilePanel } from './candidate-profile-panel';

afterEach(cleanup);

function populatedProfile(): CandidateProfile {
  return {
    schema_version: 1,
    resume: {
      summary: 'Seasoned pricing leader with a platform background.',
      headline: 'Senior Product Manager · Pricing',
      total_experience_years: 12,
      seniority: 'senior',
      skills: ['Pricing', 'SQL', 'Experimentation'],
      domains: ['FinTech', 'Marketplaces'],
      work_history: [
        {
          title: 'Senior PM',
          company: 'Acme',
          start: 'Jan 2021',
          end: null,
          is_current: true,
          highlights: ['Owned the pricing roadmap', 'Drove a 12% margin lift'],
        },
      ],
      education: [{ degree: 'BSc', field: 'Economics', institution: 'State U', year: '2011' }],
      achievements: ['Patent on dynamic pricing'],
      certifications: ['PMP'],
      languages: ['English', 'Spanish'],
    },
    ats: {
      location: 'Austin, TX',
      applied_at: '2026-06-01T00:00:00Z',
      screening_qa: [
        { question: 'Are you authorized to work in the US?', type: 'boolean', answer: 'Yes' },
      ],
      rejection: { reason: 'Withdrew from a prior loop', rejected_at: '2025-01-01T00:00:00Z' },
      stage: { id: 'stg_1', name: 'Phone screen' },
    },
    links: {
      linkedin: 'https://linkedin.com/in/example',
      github: null,
      portfolio: 'https://example.dev',
    },
    extracted_at: '2026-06-10T00:00:00Z',
    model: 'claude-sonnet-4-6',
    source: 'resume+ats',
  };
}

describe('CandidateProfilePanel — null / empty handling', () => {
  test('renders nothing when profile is null', () => {
    const { container } = render(<CandidateProfilePanel id="cpp-null" profile={null} />);
    expect(container.firstChild).toBeNull();
    expect(document.getElementById('cpp-null')).toBeNull();
  });

  test('renders nothing when profile is undefined', () => {
    const { container } = render(<CandidateProfilePanel id="cpp-undef" profile={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  test('renders nothing for an empty profile object with no meaningful content', () => {
    const empty: CandidateProfile = {
      schema_version: 1,
      resume: null,
      ats: null,
      links: null,
      extracted_at: null,
      model: null,
      source: null,
    };
    const { container } = render(<CandidateProfilePanel id="cpp-empty" profile={empty} />);
    expect(container.firstChild).toBeNull();
  });
});

describe('CandidateProfilePanel — populated', () => {
  test('renders summary, headline, skills and a link', () => {
    render(<CandidateProfilePanel id="cpp" profile={populatedProfile()} />);
    expect(document.getElementById('cpp')).not.toBeNull();
    expect(screen.getByText('Seasoned pricing leader with a platform background.')).toBeDefined();
    expect(screen.getByText('Senior Product Manager · Pricing')).toBeDefined();
    // Skills rendered as chips.
    expect(screen.getByText('Pricing')).toBeDefined();
    expect(screen.getByText('SQL')).toBeDefined();
    // Work history heading "title @ company".
    expect(screen.getByText('Senior PM @ Acme')).toBeDefined();
    // Screening Q&A.
    expect(screen.getByText('Are you authorized to work in the US?')).toBeDefined();
    // Rejection reason surfaced.
    expect(screen.getByText('Withdrew from a prior loop')).toBeDefined();
    // External links present with a real href.
    const linkedin = document.getElementById('cpp-link-linkedin') as HTMLAnchorElement | null;
    expect(linkedin?.getAttribute('href')).toBe('https://linkedin.com/in/example');
  });

  test('is null-safe when only a partial resume is present', () => {
    const partial: CandidateProfile = {
      schema_version: 1,
      resume: {
        summary: 'Just a summary, nothing else filled in.',
        headline: null,
        total_experience_years: null,
        seniority: null,
        skills: [],
        domains: [],
        work_history: [],
        education: [],
        achievements: [],
        certifications: [],
        languages: [],
      },
      ats: null,
      links: null,
      extracted_at: null,
      model: null,
      source: null,
    };
    render(<CandidateProfilePanel id="cpp-partial" profile={partial} />);
    expect(screen.getByText('Just a summary, nothing else filled in.')).toBeDefined();
    // No skills section items rendered.
    expect(document.getElementById('cpp-partial-skills')).toBeNull();
  });
});
