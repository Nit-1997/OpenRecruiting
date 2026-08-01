"use client";

import { Edit3 } from "lucide-react";

export type RatingValue = "strong_yes" | "yes" | "maybe" | "no" | "strong_no";

export const RATING_OPTIONS: { value: RatingValue; label: string; color: string }[] = [
  { value: "strong_yes", label: "Strong Yes", color: "bg-green-600 text-white hover:bg-green-700" },
  { value: "yes", label: "Yes", color: "bg-green-400 text-white hover:bg-green-500" },
  { value: "maybe", label: "Maybe", color: "bg-amber-400 text-white hover:bg-amber-500" },
  { value: "no", label: "No", color: "bg-orange-500 text-white hover:bg-orange-600" },
  { value: "strong_no", label: "Strong No", color: "bg-red-600 text-white hover:bg-red-700" },
];

export interface QuestionData {
  question_number: number;
  question_text: string;
  heading?: string;
  description: string | null;
  summary?: string | null;
}

export interface FeedbackScorecardProps {
  candidateName: string;
  roundName: string;
  interviewDate?: string | null;
  rating?: RatingValue | null;
  summary?: string;
  questions?: QuestionData[] | null;
  questionSummaries?: Record<string, string>;
  selectedSection?: "summary" | number;
  showDetails?: boolean;
  mode: "preview" | "interactive";
  onRatingChange?: (rating: RatingValue) => void;
  onSectionSelect?: (section: "summary" | number) => void;
  hideEditMode?: boolean;
}

export function FeedbackScorecard({
  candidateName,
  roundName,
  interviewDate,
  rating,
  summary,
  questions,
  questionSummaries = {},
  selectedSection,
  showDetails = true,
  mode,
  onRatingChange,
  onSectionSelect,
  hideEditMode = false,
}: FeedbackScorecardProps) {
  const isInteractive = mode === "interactive";

  const getRatingBadgeColor = (ratingValue: RatingValue | null | undefined) => {
    if (!ratingValue) return "";
    if (ratingValue === "strong_yes" || ratingValue === "yes") {
      return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400";
    }
    if (ratingValue === "maybe") {
      return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
    }
    return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
  };

  return (
    <div
      id="feedback-scorecard-card"
      className="bg-white dark:bg-secondary/80 rounded-xl border border-border shadow-sm overflow-hidden"
    >
      <div id="feedback-scorecard-header" className="p-5 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <h3 id="feedback-scorecard-candidate-name" className="font-semibold text-foreground">
            {candidateName}
          </h3>
          {isInteractive && rating && (
            <span
              id="feedback-scorecard-rating-badge"
              className={`px-3 py-1 rounded-full text-sm font-medium ${getRatingBadgeColor(rating)}`}
            >
              {RATING_OPTIONS.find((r) => r.value === rating)?.label || rating}
            </span>
          )}
        </div>
        <p id="feedback-scorecard-round-name" className="text-sm text-muted-foreground">
          {roundName}
        </p>
        {interviewDate && (
          <p id="feedback-scorecard-interview-date" className="text-xs text-muted-foreground mt-1">
            {new Date(interviewDate).toLocaleDateString()}
          </p>
        )}
        {!hideEditMode && (
          <div id="feedback-scorecard-rating-buttons" className="flex flex-wrap gap-2 mt-4">
            {RATING_OPTIONS.map((option) => {
              if (isInteractive) {
                return (
                  <button
                    key={option.value}
                    id={`feedback-scorecard-rating-${option.value}`}
                    onClick={() => onRatingChange?.(option.value)}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
                      rating === option.value
                        ? `${option.color} ring-2 ring-offset-2 ring-offset-background ring-primary`
                        : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              }
              return (
                <span
                  key={option.value}
                  id={`feedback-scorecard-rating-${option.value}`}
                  className="px-3 py-1.5 rounded-full text-xs font-medium bg-secondary text-secondary-foreground opacity-50"
                >
                  {option.label}
                </span>
              );
            })}
          </div>
        )}
      </div>

      {showDetails && (
        <>
          {isInteractive ? (
            <button
              id="feedback-scorecard-summary-section"
              onClick={() => onSectionSelect?.("summary")}
              className={`w-full p-5 text-left border-b border-border hover:bg-secondary/30 transition-colors ${
                selectedSection === "summary" ? "bg-primary/10 border-l-4 border-l-primary" : ""
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium text-sm">Overall Summary</span>
                {selectedSection === "summary" && (
                  <span id="feedback-scorecard-summary-editing-badge" className="text-xs text-primary font-medium">
                    Editing
                  </span>
                )}
              </div>
              <p className="text-sm text-muted-foreground line-clamp-3">
                {summary || "No summary yet - click to add"}
              </p>
            </button>
          ) : (
            !hideEditMode && (
              <div id="feedback-scorecard-summary-section" className="w-full p-5 text-left border-b border-border">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-sm">Overall Summary</span>
                  <Edit3 className="w-4 h-4 text-muted-foreground/50" />
                </div>
                <p className="text-sm text-muted-foreground italic">
                  AI will generate a summary from your voice feedback
                </p>
              </div>
            )
          )}

          {questions && questions.length > 0 && (
            <>
              {questions.map((question, index) => {
                const questionNum = question.question_number;
                const questionText = question.question_text || question.heading || "";
                const questionSummary = questionSummaries[String(questionNum)] || question.summary;
                const isLastQuestion = index === questions.length - 1;

                if (isInteractive) {
                  return (
                    <button
                      key={questionNum}
                      id={`feedback-scorecard-question-${questionNum}-section`}
                      onClick={() => onSectionSelect?.(questionNum)}
                      className={`w-full p-5 text-left hover:bg-secondary/30 transition-colors ${
                        !isLastQuestion ? "border-b border-border" : ""
                      } ${selectedSection === questionNum ? "bg-primary/10 border-l-4 border-l-primary" : ""}`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium text-sm line-clamp-1">
                          {questionNum}. {questionText}
                        </span>
                        {selectedSection === questionNum && (
                          <span
                            id={`feedback-scorecard-question-${questionNum}-editing-badge`}
                            className="text-xs text-primary font-medium flex-shrink-0 ml-2"
                          >
                            Editing
                          </span>
                        )}
                      </div>
                      {question.description && (
                        <p className="text-xs text-muted-foreground/70 mb-2 whitespace-pre-wrap">
                          {question.description}
                        </p>
                      )}
                      {!hideEditMode && (
                        <p className="text-sm text-muted-foreground line-clamp-2">
                          {questionSummary || "No feedback yet - click to add"}
                        </p>
                      )}
                    </button>
                  );
                }

                return (
                  <div
                    key={questionNum}
                    id={`feedback-scorecard-question-${questionNum}-section`}
                    className={`w-full p-5 text-left ${!isLastQuestion ? "border-b border-border" : ""}`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-sm line-clamp-1">
                        {questionNum}. {questionText}
                      </span>
                      {!hideEditMode && (
                        <Edit3 className="w-4 h-4 text-muted-foreground/50 flex-shrink-0 ml-2" />
                      )}
                    </div>
                    {question.description && (
                      <p className="text-xs text-muted-foreground/70 mb-2 whitespace-pre-wrap">
                        {question.description}
                      </p>
                    )}
                    {!hideEditMode && (
                      <p className="text-sm text-muted-foreground italic">No feedback yet</p>
                    )}
                  </div>
                );
              })}
            </>
          )}
        </>
      )}

      {hideEditMode && (
        <div id="feedback-scorecard-rating-buttons" className="w-full p-5 text-left border-t border-border">
          <div className="flex items-center justify-between mb-1">
            <span className="font-medium text-sm line-clamp-1">Overall verdict?</span>
          </div>
          <p className="text-xs text-muted-foreground/70 mb-2 line-clamp-1">
            {RATING_OPTIONS.map((option) => option.label).join(" / ")}
          </p>
        </div>
      )}
    </div>
  );
}
