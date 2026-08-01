'use client';

import { Check, Loader2, Mic, MicOff } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/toast';
import { useSpeechToText } from '@/hooks/use-speech-to-text';
import { cn } from '@/lib/utils';
import {
  approveFeedback,
  editFeedback,
  type FeedbackRating,
  type FeedbackReview,
} from '@/services/public-feedback';

const RATINGS: { value: FeedbackRating; label: string }[] = [
  { value: 'strong_yes', label: 'Strong Yes' },
  { value: 'yes', label: 'Yes' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'no', label: 'No' },
  { value: 'strong_no', label: 'Strong No' },
];

interface DictationFieldProps {
  id: string;
  value: string;
  placeholder?: string;
  rows?: number;
  sessionToken: string;
  onChange: (value: string) => void;
}

function DictationField({
  id,
  value,
  placeholder,
  rows = 4,
  sessionToken,
  onChange,
}: DictationFieldProps) {
  const baseRef = useRef(value);

  const handleTranscript = useCallback(
    (transcript: string, isFinal: boolean) => {
      if (!isFinal) return;
      const next = baseRef.current ? `${baseRef.current} ${transcript}` : transcript;
      baseRef.current = next;
      onChange(next);
    },
    [onChange],
  );

  const { isListening, isConnecting, startListening, stopListening } = useSpeechToText({
    onTranscript: handleTranscript,
    feedbackSessionToken: sessionToken,
  });

  const toggle = () => {
    if (isListening || isConnecting) {
      stopListening();
    } else {
      baseRef.current = value;
      void startListening();
    }
  };

  return (
    <div className="relative">
      <Textarea
        id={id}
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(e) => {
          baseRef.current = e.target.value;
          onChange(e.target.value);
        }}
        className="pr-11"
      />
      <button
        id={`${id}-mic`}
        type="button"
        onClick={toggle}
        aria-label={isListening ? 'Stop dictation' : 'Dictate'}
        className={cn(
          'absolute top-2 right-2 inline-flex h-7 w-7 items-center justify-center rounded-full transition-colors',
          isListening
            ? 'bg-red-600 text-white'
            : 'bg-surface text-text-secondary hover:text-charcoal',
        )}
      >
        {isConnecting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : isListening ? (
          <MicOff className="h-4 w-4" />
        ) : (
          <Mic className="h-4 w-4" />
        )}
      </button>
    </div>
  );
}

interface FeedbackEditProps {
  token: string;
  sessionToken: string;
  review: FeedbackReview;
  onApproved: () => void;
  onRerecord: () => void;
}

export function FeedbackEdit({
  token,
  sessionToken,
  review,
  onApproved,
  onRerecord,
}: FeedbackEditProps) {
  const { showToast } = useToast();

  const [summary, setSummary] = useState(review.summary ?? '');
  const [rating, setRating] = useState<FeedbackRating | null>(review.rating ?? null);
  const [questionSummaries, setQuestionSummaries] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const q of review.question_summaries ?? []) {
      init[String(q.question_number)] = q.summary ?? '';
    }
    return init;
  });
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);

  const dirtyRef = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced autosave on any change (skips the initial mount).
  useEffect(() => {
    if (!dirtyRef.current) {
      dirtyRef.current = true;
      return;
    }
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      setSaving(true);
      try {
        await editFeedback(token, sessionToken, {
          summary,
          question_summaries: questionSummaries,
          ...(rating ? { rating } : {}),
        });
      } catch {
        showToast('Could not save your changes — they will retry.', 'error');
      } finally {
        setSaving(false);
      }
    }, 500);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [summary, rating, questionSummaries, token, sessionToken, showToast]);

  const approve = async () => {
    setApproving(true);
    try {
      // Flush any pending edit before approving.
      if (saveTimer.current) clearTimeout(saveTimer.current);
      await editFeedback(token, sessionToken, {
        summary,
        question_summaries: questionSummaries,
        ...(rating ? { rating } : {}),
      });
      await approveFeedback(token, sessionToken);
      onApproved();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Could not submit feedback.', 'error');
      setApproving(false);
    }
  };

  const questions = review.question_summaries ?? [];

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="font-semibold text-charcoal text-lg">Review &amp; submit feedback</h1>
        <p className="text-[13px] text-text-secondary">
          {review.candidate_name} · {review.round_name}
        </p>
      </header>

      <section className="flex flex-col gap-2">
        <span className="font-medium text-[13px] text-charcoal">Overall recommendation</span>
        <div className="flex flex-wrap gap-2">
          {RATINGS.map((r) => (
            <button
              key={r.value}
              id={`feedback-rating-${r.value}`}
              type="button"
              onClick={() => setRating(r.value)}
              className={cn(
                'h-9 rounded-full border px-4 font-medium text-[13px] transition-colors',
                rating === r.value
                  ? 'border-charcoal bg-charcoal text-white'
                  : 'border-border bg-tile text-text-secondary hover:border-border-strong hover:text-charcoal',
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <span className="font-medium text-[13px] text-charcoal">Summary</span>
        <DictationField
          id="feedback-summary"
          value={summary}
          rows={5}
          placeholder="Overall summary of the candidate's performance…"
          sessionToken={sessionToken}
          onChange={setSummary}
        />
      </section>

      {questions.length > 0 && (
        <section className="flex flex-col gap-4">
          <span className="font-medium text-[13px] text-charcoal">Scorecard</span>
          {questions.map((q) => {
            const key = String(q.question_number);
            return (
              <div key={key} className="flex flex-col gap-1.5">
                <span className="font-medium text-[13px] text-charcoal">{q.question_text}</span>
                {q.description && (
                  <span className="text-[12px] text-text-muted">{q.description}</span>
                )}
                <DictationField
                  id={`feedback-q-${key}`}
                  value={questionSummaries[key] ?? ''}
                  sessionToken={sessionToken}
                  onChange={(v) => setQuestionSummaries((prev) => ({ ...prev, [key]: v }))}
                />
              </div>
            );
          })}
        </section>
      )}

      <footer className="flex items-center justify-between gap-3 border-border border-t pt-4">
        <div className="flex items-center gap-2 text-[12px] text-text-muted">
          {saving ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…
            </>
          ) : (
            <>
              <Check className="h-3.5 w-3.5 text-green-600" /> Saved
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button id="feedback-rerecord" variant="ghost" onClick={onRerecord} disabled={approving}>
            Re-record
          </Button>
          <Button id="feedback-approve" onClick={approve} disabled={approving}>
            {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Approve & submit'}
          </Button>
        </div>
      </footer>
    </div>
  );
}
