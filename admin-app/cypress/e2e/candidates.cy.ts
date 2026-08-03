describe('Candidates Page', () => {
  const reqId = 'req-1'

  beforeEach(() => {
    cy.loginAsAdmin()

    cy.interceptAdminAPI('GET', `requisitions/${reqId}`, {
      id: reqId,
      organization_id: 'org-1',
      role_title: 'Senior Frontend Engineer',
      role_location: 'San Francisco, CA',
      experience_display: '5-10 years',
      status: 'planned',
    })

    cy.fixture('candidates.json').then((data) => {
      cy.interceptAdminAPI('GET', `requisitions/${reqId}/candidates`, data)
    })
  })

  it('displays the candidate list with names and emails', () => {
    cy.visit(`/requisitions/${reqId}/candidates`)
    cy.get('#candidates-list-page').should('be.visible')
    cy.get('#candidates-page-title').should('contain', 'Senior Frontend Engineer')
    cy.get('#candidates-table').should('be.visible')
    cy.contains('Jane Doe').should('be.visible')
    cy.contains('John Roe').should('be.visible')
  })

  it('adds a candidate via the modal', () => {
    cy.intercept('POST', `http://localhost:8000/api/v1/admin/requisitions/${reqId}/candidates`, {
      statusCode: 200,
      body: { id: 'cand-new', name: 'New Candidate', email: 'new@example.com' },
    }).as('addCandidate')

    cy.visit(`/requisitions/${reqId}/candidates`)
    cy.get('#add-candidate-btn').click()
    cy.get('#add-candidate-modal').should('be.visible')
    cy.get('#candidate-name').type('New Candidate')
    cy.get('#candidate-email').type('new@example.com')
    cy.get('#add-candidate-submit').click()
    cy.wait('@addCandidate')
  })

  it('displays status badges for each candidate', () => {
    cy.visit(`/requisitions/${reqId}/candidates`)
    cy.get('#candidate-status-cand-1').should('contain', 'Active')
  })

  it('shows round progress indicators', () => {
    cy.visit(`/requisitions/${reqId}/candidates`)
    cy.get('#candidate-progress-cand-1').should('contain', '1/2')
  })

  it('navigates to the scorecard page', () => {
    cy.visit(`/requisitions/${reqId}/candidates`)
    cy.get('#candidate-edit-scorecard-cand-1').should('have.attr', 'href')
      .and('include', `/requisitions/${reqId}/candidates/cand-1/scorecard`)
  })
})
