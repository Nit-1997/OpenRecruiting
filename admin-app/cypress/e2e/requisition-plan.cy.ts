describe('Requisition Plan Page', () => {
  const reqId = 'req-1'

  beforeEach(() => {
    cy.loginAsAdmin()

    cy.fixture('requisitions.json').then((data) => {
      const req = {
        ...data.requisitions[0],
        intake_transcript: null,
        intake_processing_status: null,
        intake_processing_error: null,
      }
      cy.interceptAdminAPI('GET', `requisitions/${reqId}`, req)
      cy.interceptAdminAPI('GET', `organizations/${req.organization_id}`, {
        id: req.organization_id,
        name: 'Acme Corp',
      })
    })

    cy.interceptAdminAPI('GET', `requisitions/${reqId}/plan`, { rounds: [] })
  })

  it('displays the transcript input form with page title', () => {
    cy.visit(`/requisitions/${reqId}/plan`)
    cy.get('#plan-input-page').should('be.visible')
    cy.get('#plan-title').should('contain', 'Senior Frontend Engineer')
    cy.get('#plan-transcript-card').should('be.visible')
    cy.get('#plan-transcript-input').should('be.visible')
    cy.get('#generate-plan-btn').should('be.visible').and('be.disabled')
  })

  it('enables generate button when transcript is entered', () => {
    cy.visit(`/requisitions/${reqId}/plan`)
    cy.get('#generate-plan-btn').should('be.disabled')
    cy.get('#plan-transcript-input').type('Candidate needs strong React skills')
    cy.get('#generate-plan-btn').should('not.be.disabled')
  })

  it('shows processing state after generating plan', () => {
    cy.intercept('POST', 'http://localhost:8000/api/v1/admin/intake-jobs', {
      statusCode: 200,
      body: { status: 'accepted', requisition_id: reqId },
    }).as('triggerGeneration')

    cy.intercept('GET', `http://localhost:8000/api/v1/admin/intake-jobs/${reqId}/status`, {
      statusCode: 200,
      body: { intake_processing_status: 'processing' },
    }).as('pollStatus')

    cy.visit(`/requisitions/${reqId}/plan`)
    cy.get('#plan-transcript-input').type('Candidate needs strong React and TypeScript skills')
    cy.get('#generate-plan-btn').click()
    cy.wait('@triggerGeneration')
    cy.get('#plan-processing-card').should('be.visible')
    cy.get('#plan-processing-title').should('contain', 'Generating Interview Plan')
  })

  it('loads existing transcript from requisition', () => {
    cy.fixture('requisitions.json').then((data) => {
      const req = {
        ...data.requisitions[0],
        intake_transcript: 'Existing transcript from intake call',
        intake_processing_status: null,
        intake_processing_error: null,
      }
      cy.interceptAdminAPI('GET', `requisitions/${reqId}`, req)
    })

    cy.visit(`/requisitions/${reqId}/plan`)
    cy.get('#plan-transcript-input').should('have.value', 'Existing transcript from intake call')
    cy.get('#generate-plan-btn').should('not.be.disabled')
  })
})
