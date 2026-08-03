describe('Assessments Page', () => {
  beforeEach(() => {
    cy.loginAsAdmin()
  })

  it('displays the assessment template list', () => {
    cy.fixture('assessment-templates.json').then((data) => {
      cy.interceptAdminAPI('GET', 'assessment-templates', data)
    })

    cy.visit('/assessments')
    cy.get('#assessments-page').should('be.visible')
    cy.get('#assessments-title').should('contain', 'Assessment Templates')
    cy.get('#templates-grid').should('be.visible')
    cy.contains('Frontend System Design').should('be.visible')
    cy.contains('Product Strategy Assessment').should('be.visible')
  })

  it('navigates to the create template page', () => {
    cy.interceptAdminAPI('GET', 'assessment-templates', { templates: [] })

    cy.visit('/assessments')
    cy.get('#new-template-btn').click()
    cy.url().should('include', '/assessments/new')
  })

  it('shows empty state when no templates exist', () => {
    cy.interceptAdminAPI('GET', 'assessment-templates', { templates: [] })

    cy.visit('/assessments')
    cy.get('#templates-empty').should('be.visible')
    cy.contains('No templates found').should('be.visible')
  })

  it('deletes a template via the confirmation modal', () => {
    cy.fixture('assessment-templates.json').then((data) => {
      cy.interceptAdminAPI('GET', 'assessment-templates', data)
    })

    cy.intercept('DELETE', 'http://localhost:8000/api/v1/admin/assessment-templates/tmpl-1', {
      statusCode: 200,
      body: {},
    }).as('deleteTemplate')

    cy.visit('/assessments')
    cy.get('#template-tmpl-1').find('button[title="Delete"]').click()
    cy.get('#delete-modal').should('be.visible')
    cy.contains('Delete Template?').should('be.visible')
    cy.get('#delete-modal').find('button').contains('Delete').click()
    cy.wait('@deleteTemplate')
    cy.contains('Frontend System Design').should('not.exist')
  })

  it('filters templates by status', () => {
    cy.fixture('assessment-templates.json').then((data) => {
      cy.interceptAdminAPI('GET', 'assessment-templates', data)
    })

    cy.visit('/assessments')
    cy.get('#status-filter').contains('Draft').click()
    cy.contains('Product Strategy Assessment').should('be.visible')
    cy.contains('Frontend System Design').should('not.exist')

    cy.get('#status-filter').contains('Published').click()
    cy.contains('Frontend System Design').should('be.visible')
    cy.contains('Product Strategy Assessment').should('not.exist')

    cy.get('#status-filter').contains('All').click()
    cy.get('[id^="template-"]').should('have.length', 3)
  })
})
