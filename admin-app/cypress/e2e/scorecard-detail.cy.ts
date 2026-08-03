describe("Scorecard Detail Page", () => {
  const reqId = "req-1";
  const candidateId = "cand-1";

  const mockCandidate = {
    id: candidateId,
    name: "Jane Doe",
    email: "jane@example.com",
    requisition_id: reqId,
    requisition_title: "Senior Frontend Engineer",
    status: "active",
    final_verdict: null,
    rounds: [
      {
        id: "cr-1",
        round_number: 1,
        round_name: "Technical Screen",
        round_description: "Technical coding assessment",
        status: "completed",
        outcome: "advance",
        scheduled_at: "2024-07-05T14:00:00Z",
        completed_at: "2024-07-05T15:00:00Z",
        meeting_url: null,
        round_type: "interview",
        assessment_instance: null,
        summary: "Strong problem solving skills",
        rating: "advance",
        question_summaries: null,
        feedback_status: "completed",
        recording_url: "https://example.com/recording.mp4",
        recall_bot_id: "bot-1",
        feedback_questions: [
          {
            id: "fq-1",
            question_number: 1,
            heading: "Problem Solving",
            description: "Rate problem solving ability",
            summary: "Excellent algorithmic thinking",
            feedback: [
              {
                id: "fb-1",
                feedback_data: "Good approach to breaking down problems",
                evidence: [],
                evidence_status: null,
                source: "ai",
              },
            ],
          },
          {
            id: "fq-2",
            question_number: 2,
            heading: "Communication",
            description: "Rate communication clarity",
            summary: "Clear and concise explanations",
            feedback: [],
          },
        ],
      },
    ],
  };

  beforeEach(() => {
    cy.loginAsAdmin();

    cy.intercept(
      "GET",
      `http://localhost:8000/api/v1/admin/candidates/${candidateId}`,
      { statusCode: 200, body: mockCandidate }
    ).as("fetchCandidate");
  });

  it("loads scorecard with AI feedback questions", () => {
    cy.visit(`/requisitions/${reqId}/candidates/${candidateId}/scorecard`);
    cy.wait("@fetchCandidate");
    cy.get("#scorecard-editor-page").should("be.visible");
    cy.get("#scorecard-candidate-name").should("contain", "Jane Doe");
    cy.get("#scorecard-questions-section").should("be.visible");
    cy.contains("Problem Solving").should("be.visible");
    cy.contains("Good approach to breaking down problems").should("be.visible");
  });

  it("shows question summaries for each criterion", () => {
    cy.visit(`/requisitions/${reqId}/candidates/${candidateId}/scorecard`);
    cy.wait("@fetchCandidate");
    cy.contains("Excellent algorithmic thinking").should("be.visible");
    cy.contains("Clear and concise explanations").should("be.visible");
  });

  it("shows rating and summary fields", () => {
    cy.visit(`/requisitions/${reqId}/candidates/${candidateId}/scorecard`);
    cy.wait("@fetchCandidate");
    cy.get("#scorecard-round-summary-section").should("be.visible");
    cy.get("#scorecard-summary-input").should("have.value", "Strong problem solving skills");
    cy.get("#scorecard-rating-select").should("be.visible");
  });

  it("trigger reprocess via AI tab", () => {
    cy.intercept(
      "GET",
      `http://localhost:8000/api/v1/admin/candidate-rounds/cr-1/transcript-status`,
      {
        statusCode: 200,
        body: {
          can_process_existing: true,
          has_interview_segments: true,
          has_feedback_timestamp: false,
          has_stored_feedback: false,
        },
      }
    ).as("transcriptStatus");

    cy.visit(`/requisitions/${reqId}/candidates/${candidateId}/scorecard`);
    cy.wait("@fetchCandidate");
    cy.get("#ai-process-tab-btn").click();
    cy.get("#ai-process-content").should("be.visible");
    cy.wait("@transcriptStatus");
    cy.get("#process-existing-btn").should("be.visible");
  });
});
