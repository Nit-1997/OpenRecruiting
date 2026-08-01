'use client';

import {
  Award,
  Briefcase,
  ExternalLink,
  MapPin,
  MessageSquare,
  Sparkles,
  XCircle,
} from 'lucide-react';
import type { CandidateProfile, ResumeSeniority, ResumeWorkEntry } from '@/domain/candidate';

// Recruiter-facing panel for the structured candidate profile produced by ATS
// resume enrichment (candidates.profile JSONB). Purely presentational: it
// receives the already-fetched profile object; it does NO fetching. Renders
// nothing for manual / non-ATS / not-yet-enriched candidates (profile falsy).
//
// Every sub-field is optional — the enrichment model fills what it can — so each
// section guards its own presence and the panel only renders when there is at
// least one thing worth showing.

const SENIORITY_LABEL: Record<ResumeSeniority, string> = {
  early: 'Early career',
  mid: 'Mid-level',
  senior: 'Senior',
  staff: 'Staff',
  principal: 'Principal',
};

function hasText(value: string | null | undefined): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

// "Jan 2021 — Present" style range from the loosely-typed start/end strings.
// Returns null when neither bound is known so the caller can omit the line.
function formatRange(entry: ResumeWorkEntry): string | null {
  const start = hasText(entry.start) ? entry.start.trim() : null;
  const end = entry.is_current ? 'Present' : hasText(entry.end) ? entry.end.trim() : null;
  if (start && end) return `${start} — ${end}`;
  if (start) return `${start} — `;
  if (end) return end;
  return null;
}

function formatExperience(years: number | null | undefined): string | null {
  if (typeof years !== 'number' || !Number.isFinite(years) || years <= 0) return null;
  const rounded = Math.round(years * 10) / 10;
  return `${rounded} yr${rounded === 1 ? '' : 's'} experience`;
}

function ChipRow({ id, label, items }: { id: string; label: string; items: string[] }) {
  const clean = items.map((s) => s?.trim()).filter((s): s is string => !!s && s.length > 0);
  if (clean.length === 0) return null;
  return (
    <div id={id} className="flex flex-col gap-1.5">
      <span
        id={`${id}-label`}
        className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]"
      >
        {label}
      </span>
      <div id={`${id}-items`} className="flex flex-wrap gap-1.5">
        {clean.map((item, i) => (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: enriched chip list is a stable, ordered set
            key={`${item}-${i}`}
            id={`${id}-item-${i}`}
            className="inline-flex items-center rounded-full border border-border bg-surface px-2.5 py-0.5 font-medium text-[11.5px] text-text-secondary"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

export function CandidateProfilePanel({
  id,
  profile,
}: {
  id: string;
  profile: CandidateProfile | null | undefined;
}) {
  if (!profile) return null;

  const resume = profile.resume ?? null;
  const ats = profile.ats ?? null;
  const links = profile.links ?? null;

  const seniorityLabel =
    resume?.seniority != null ? (SENIORITY_LABEL[resume.seniority] ?? resume.seniority) : null;
  const experienceLabel = formatExperience(resume?.total_experience_years);

  const workHistory = (resume?.work_history ?? []).filter(
    (w) => hasText(w.title) || hasText(w.company),
  );
  const screeningQa = (ats?.screening_qa ?? []).filter(
    (qa) => hasText(qa?.question) || hasText(qa?.answer),
  );

  const linkEntries: Array<{ key: string; href: string; label: string }> = [];
  if (links) {
    if (hasText(links.linkedin)) {
      linkEntries.push({ key: 'linkedin', href: links.linkedin, label: 'LinkedIn' });
    }
    if (hasText(links.github)) {
      linkEntries.push({ key: 'github', href: links.github, label: 'GitHub' });
    }
    if (hasText(links.portfolio)) {
      linkEntries.push({ key: 'portfolio', href: links.portfolio, label: 'Portfolio' });
    }
  }

  // Decide whether the panel has anything worth showing. A profile object can
  // exist with every meaningful sub-field empty (e.g. an ATS row with only a
  // schema_version) — in that case we render nothing rather than an empty card.
  const hasMetaRow =
    hasText(ats?.location) ||
    hasText(seniorityLabel) ||
    !!experienceLabel ||
    hasText(ats?.stage?.name);
  const hasContent =
    hasText(resume?.summary) ||
    hasText(resume?.headline) ||
    hasMetaRow ||
    (resume?.skills?.length ?? 0) > 0 ||
    (resume?.domains?.length ?? 0) > 0 ||
    workHistory.length > 0 ||
    screeningQa.length > 0 ||
    !!ats?.rejection ||
    linkEntries.length > 0;

  if (!hasContent) return null;

  return (
    <section
      id={id}
      aria-label="Candidate background"
      className="rounded-[16px] border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] print:break-inside-avoid print:shadow-none"
    >
      <header id={`${id}-header`} className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-full bg-surface text-text-muted"
          >
            <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />
          </span>
          <h3 className="font-display text-[20px] text-text-primary leading-tight tracking-[-0.005em]">
            Candidate background
          </h3>
        </div>
        <span
          id={`${id}-source-badge`}
          className="inline-flex items-center gap-1.5 rounded-full border border-cortex-500/30 bg-white px-2.5 py-1 font-medium font-mono text-[10px] text-cortex-500 uppercase tracking-[0.14em]"
        >
          <Sparkles strokeWidth={1.75} className="h-3 w-3" aria-hidden />
          From resume
        </span>
      </header>

      {hasText(resume?.headline) && (
        <p
          id={`${id}-headline`}
          className="mb-1 font-medium text-[14px] text-text-primary leading-snug"
        >
          {resume.headline}
        </p>
      )}

      {hasMetaRow && (
        <div id={`${id}-meta`} className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {hasText(ats?.location) && (
            <span
              id={`${id}-location`}
              className="inline-flex items-center gap-1 text-[12px] text-text-muted"
            >
              <MapPin strokeWidth={1.75} className="h-3 w-3 shrink-0" aria-hidden />
              {ats.location}
            </span>
          )}
          {hasText(seniorityLabel) && (
            <span
              id={`${id}-seniority`}
              className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[10px] text-text-secondary uppercase tracking-[0.12em]"
            >
              {seniorityLabel}
            </span>
          )}
          {experienceLabel && (
            <span id={`${id}-experience`} className="text-[12px] text-text-muted">
              {experienceLabel}
            </span>
          )}
          {hasText(ats?.stage?.name) && (
            <span id={`${id}-stage`} className="text-[12px] text-text-muted">
              Stage · {ats.stage.name}
            </span>
          )}
        </div>
      )}

      {hasText(resume?.summary) && (
        <p
          id={`${id}-summary`}
          className="mb-4 whitespace-pre-wrap text-[13.5px] text-text-secondary leading-[1.6]"
        >
          {resume.summary}
        </p>
      )}

      <div id={`${id}-tags`} className="flex flex-col gap-3">
        <ChipRow id={`${id}-skills`} label="Skills" items={resume?.skills ?? []} />
        <ChipRow id={`${id}-domains`} label="Domains" items={resume?.domains ?? []} />
      </div>

      {workHistory.length > 0 && (
        <div id={`${id}-work`} className="mt-4 flex flex-col gap-2">
          <div id={`${id}-work-header`} className="flex items-center gap-1.5">
            <Briefcase strokeWidth={1.75} className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Work history
            </span>
          </div>
          <ul id={`${id}-work-list`} className="flex flex-col gap-2">
            {workHistory.map((entry, i) => {
              const range = formatRange(entry);
              const title = hasText(entry.title) ? entry.title : null;
              const company = hasText(entry.company) ? entry.company : null;
              const heading = [title, company].filter(Boolean).join(' @ ');
              const highlights = (entry.highlights ?? [])
                .map((h) => h?.trim())
                .filter((h): h is string => !!h && h.length > 0)
                .slice(0, 3);
              return (
                <li
                  // biome-ignore lint/suspicious/noArrayIndexKey: enriched work history is a stable, ordered set
                  key={`${heading}-${i}`}
                  id={`${id}-work-${i}`}
                  className="rounded-[10px] border border-border bg-surface/40 px-4 py-3"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                    <span
                      id={`${id}-work-${i}-heading`}
                      className="font-medium text-[13px] text-text-primary"
                    >
                      {heading || 'Role'}
                    </span>
                    {range && (
                      <span
                        id={`${id}-work-${i}-range`}
                        className="font-mono text-[10.5px] text-text-faint tabular-nums"
                      >
                        {range}
                      </span>
                    )}
                  </div>
                  {highlights.length > 0 && (
                    <ul
                      id={`${id}-work-${i}-highlights`}
                      className="mt-1.5 flex list-disc flex-col gap-0.5 pl-4 text-[12.5px] text-text-secondary leading-[1.5]"
                    >
                      {highlights.map((h, j) => (
                        <li
                          // biome-ignore lint/suspicious/noArrayIndexKey: highlight list is a stable, ordered set per role
                          key={`${i}-${j}`}
                          id={`${id}-work-${i}-highlight-${j}`}
                        >
                          {h}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <ChipRow
        id={`${id}-certifications`}
        label="Certifications"
        items={resume?.certifications ?? []}
      />
      <ChipRow id={`${id}-languages`} label="Languages" items={resume?.languages ?? []} />

      {screeningQa.length > 0 && (
        <div id={`${id}-screening`} className="mt-4 flex flex-col gap-2">
          <div id={`${id}-screening-header`} className="flex items-center gap-1.5">
            <MessageSquare strokeWidth={1.75} className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Screening questions
            </span>
          </div>
          <ul id={`${id}-screening-list`} className="flex flex-col gap-2">
            {screeningQa.map((qa, i) => (
              <li
                // biome-ignore lint/suspicious/noArrayIndexKey: enriched screening Q&A is a stable, ordered set
                key={`${qa.question}-${i}`}
                id={`${id}-screening-${i}`}
                className="rounded-[10px] border border-border bg-surface/40 px-4 py-3"
              >
                {hasText(qa.question) && (
                  <p
                    id={`${id}-screening-${i}-q`}
                    className="font-medium text-[12.5px] text-text-primary leading-snug"
                  >
                    {qa.question}
                  </p>
                )}
                {hasText(qa.answer) && (
                  <p
                    id={`${id}-screening-${i}-a`}
                    className="mt-1 whitespace-pre-wrap text-[12.5px] text-text-secondary leading-[1.55]"
                  >
                    {qa.answer}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(resume?.achievements?.length ?? 0) > 0 && resume && (
        <div id={`${id}-achievements`} className="mt-4 flex flex-col gap-2">
          <div id={`${id}-achievements-header`} className="flex items-center gap-1.5">
            <Award strokeWidth={1.75} className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Achievements
            </span>
          </div>
          <ul
            id={`${id}-achievements-list`}
            className="flex list-disc flex-col gap-0.5 pl-4 text-[12.5px] text-text-secondary leading-[1.5]"
          >
            {resume.achievements
              .map((a) => a?.trim())
              .filter((a): a is string => !!a && a.length > 0)
              .map((a, i) => (
                <li
                  // biome-ignore lint/suspicious/noArrayIndexKey: enriched achievements is a stable, ordered set
                  key={`${a}-${i}`}
                  id={`${id}-achievement-${i}`}
                >
                  {a}
                </li>
              ))}
          </ul>
        </div>
      )}

      {ats?.rejection && hasText(ats.rejection.reason) && (
        <div
          id={`${id}-rejection`}
          className="mt-4 flex items-start gap-2 rounded-[10px] border border-[#FECACA] bg-[#FEF2F2] px-3.5 py-2.5"
        >
          <XCircle
            strokeWidth={1.75}
            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#B91C1C]"
            aria-hidden
          />
          <div className="min-w-0">
            <p className="font-medium font-mono text-[#B91C1C] text-[10px] uppercase tracking-[0.14em]">
              Previously rejected in ATS
            </p>
            <p
              id={`${id}-rejection-reason`}
              className="mt-0.5 text-[#991B1B] text-[12.5px] leading-[1.5]"
            >
              {ats.rejection.reason}
            </p>
          </div>
        </div>
      )}

      {linkEntries.length > 0 && (
        <div id={`${id}-links`} className="mt-4 flex flex-wrap gap-2">
          {linkEntries.map((link) => (
            <a
              key={link.key}
              id={`${id}-link-${link.key}`}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-2.5 py-1 font-medium text-[11.5px] text-text-secondary transition-colors hover:border-text-primary hover:text-text-primary"
            >
              <ExternalLink strokeWidth={1.75} className="h-3 w-3" aria-hidden />
              {link.label}
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
