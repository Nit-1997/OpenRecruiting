describe('Scorecard Page', () => {
  const reqId = 'req-1'
  const candidateId = 'cand-1'

  const mockCandidate = {
    id: candidateId,
    name: 'Jane Doe',
    email: 'jane@example.com',
    requisition_id: reqId,
    requisition_title: 'Senior Frontend Engineer',
    status: 'active',
    final_verdict: null,
    rounds: [
      {
        id: 'cr-1',
        round_number: 1,
        round_name: 'Technical Screen',
        round_description: 'Technical coding assessment',
        status: 'completed',
        outcome: 'advance',
        scheduled_at: '2024-07-05T14:00:00Z',
        completed_at: '2024-07-05T15:00:00Z',
        meeting_url: null,
        round_type: 'interview',
        assessment_instance: null,
        summary: 'Strong problem solving skills demonstrated',
        rating: 'advance',
        question_summaries: null,
        feedback_status: 'completed',
        recording_url: 'https://example.com/recording.mp4',
        recall_bot_id: 'bot-1',
        feedback_questions: [
          {
            id: 'fq-1',
            question_number: 1,
            heading: 'Problem Solving',
            description: 'Rate problem solving ability',
            summary: 'Candidate showed excellent algorithmic thinking',
            feedback: [
              {
                id: 'fb-1',
                feedback_data: 'Good approach to breaking down problems',
                evidence: [],
                evidence_status: null,
                source: 'ai',
              },
            ],
          },
          {
            id: 'fq-2',
            question_number: 2,
            heading: 'Communication',
            description: 'Rate communication clarity',
            summary: 'Clear and concise explanations',
            feedback: [],
          },
        ],
      },
      {
        id: 'cr-2',
        round_number: 2,
        round_name: 'System Design',
        round_description: 'Architecture discussion',
        status: 'scheduled',
        outcome: null,
        scheduled_at: '2024-07-20T14:00:00Z',
        completed_at: null,
        meeting_url: 'https://meet.example.com/abc',
        round_type: 'interview',
        assessment_instance: null,
        summary: null,
        rating: null,
        question_summaries: null,
        feedback_status: null,
        recording_url: null,
        recall_bot_id: null,
        feedback_questions: [
          {
            id: 'fq-3',
            question_number: 1,
            heading: 'Design Thinking',
            description: 'Rate system design approach',
            summary: null,
            feedback: [],
          },
        ],
      },
    ],
  }

  beforeEach(() => {
    cy.loginAsAdmin()

    cy.intercept(
      'GET',
      `http://localhost:8000/api/v1/admin/candidates/${candidateId}`,
      {
        statusCode: 200,
        body: mockCandidate,
      }
    ).as('fetchScorecard')
  })

  it('displays feedback questions with AI summaries', () => {
    cy.visit(`/requisitions/${reqId}/candidates/${candidateId}/scorecard`)
    cy.wait('@fetchScorecard')
    cy.get('#scorecard-editor-page').should('be.visible')
    cy.get('#scorecard-candidate-name').should('contain', 'Jane Doe')
    cy.get('#scorecard-round-title').should('contain', 'Technical Screen')
    cy.get('#scorecard-questions-section').should('be.visible')
    cy.contains('Problem Solving').should('be.visible')
    cy.contains('Communication').should('be.visible')
  })

  it('shows the round summary and rating fields', () => {
    cy.visit(`/requisitions/${reqId}/candidates/${candidateId}/scorecard`)
    cy.wait('@fetchScorecard')
    cy.get('#scorecard-round-summary-section').should('be.visible')
    cy.get('#scorecard-summary-input').should(
      'have.value',
      'Strong problem solving skills demonstrated'
    )
    cy.get('#scorecard-rating-select').should('be.visible')
  })

  it('navigates between rounds using the sidebar', () => {
    cy.visit(`/requisitions/${reqId}/candidates/${candidateId}/scorecard`)
    cy.wait('@fetchScorecard')
    cy.get('#scorecard-round-btn-cr-2').click()
    cy.get('#scorecard-round-title').should('contain', 'System Design')
  })

  it('displays the save button for the scorecard', () => {
    cy.visit(`/requisitions/${reqId}/candidates/${candidateId}/scorecard`)
    cy.wait('@fetchScorecard')
    cy.get('#scorecard-save-btn').should('be.visible')
  })
})
