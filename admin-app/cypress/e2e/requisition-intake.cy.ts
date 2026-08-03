describe('Requisition Intake Page', () => {
  const reqId = 'req-1'

  beforeEach(() => {
    cy.loginAsAdmin()

    cy.fixture('requisitions.json').then((data) => {
      const req = data.requisitions[0]
      cy.interceptAdminAPI('GET', `requisitions/${reqId}`, req)
      cy.interceptAdminAPI('GET', `organizations/${req.organization_id}`, {
        id: req.organization_id,
        name: 'Acme Corp',
      })
    })
  })

  it('displays the intake form with existing data', () => {
    cy.visit(`/requisitions/${reqId}/intake`)
    cy.get('#intake-page').should('be.visible')
    cy.get('#intake-title').should('contain', 'Senior Frontend Engineer')
    cy.get('#job-description-input').should(
      'have.value',
      'Build and maintain frontend applications'
    )
    cy.get('#must-have-tags').should('contain', 'React')
    cy.get('#must-have-tags').should('contain', 'TypeScript')
  })

  it('updates job description, skills, and notes then saves', () => {
    cy.intercept('PUT', `http://localhost:8000/api/v1/admin/requisitions/${reqId}/intake`, {
      statusCode: 200,
      body: { id: reqId, status: 'intake_pending' },
    }).as('saveIntake')

    cy.visit(`/requisitions/${reqId}/intake`)
    cy.get('#job-description-input').clear().type('Updated job description text')
    cy.get('#additional-notes-input').clear().type('Added some notes')
    cy.get('#save-intake-btn').click()
    cy.wait('@saveIntake')
    cy.get('#save-success-message').should('be.visible')
  })

  it('proceeds to the plan step after saving', () => {
    cy.intercept('PUT', `http://localhost:8000/api/v1/admin/requisitions/${reqId}/intake`, {
      statusCode: 200,
      body: { id: reqId, status: 'intake_pending' },
    }).as('saveIntake')

    cy.visit(`/requisitions/${reqId}/intake`)
    cy.get('#proceed-to-plan-btn').click()
    cy.wait('@saveIntake')
    cy.url().should('include', `/requisitions/${reqId}/plan`)
  })
})
