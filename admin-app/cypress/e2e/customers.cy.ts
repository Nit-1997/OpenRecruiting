describe('Customers Page', () => {
  beforeEach(() => {
    cy.loginAsAdmin()
  })

  it('displays a list of active organizations', () => {
    cy.fixture('organizations.json').then((data) => {
      cy.interceptAdminAPI('GET', 'organizations', data)
      cy.interceptAdminAPI('GET', 'organizations/archived', { organizations: [] })
    })

    cy.visit('/customers')
    cy.get('#customers-page').should('be.visible')
    cy.get('#page-title').should('contain', 'Organizations')
    cy.get('#organizations-grid').should('be.visible')
    cy.get('[id^="organization-card-"]').should('have.length', 3)
    cy.contains('Acme Corp').should('be.visible')
    cy.contains('Globex Inc').should('be.visible')
  })

  it('shows empty state when no organizations exist', () => {
    cy.interceptAdminAPI('GET', 'organizations', { organizations: [] })
    cy.interceptAdminAPI('GET', 'organizations/archived', { organizations: [] })

    cy.visit('/customers')
    cy.get('#empty-state').should('be.visible')
    cy.contains('No organizations yet').should('be.visible')
    cy.contains('Add Organization').should('be.visible')
  })

  it('navigates to the create organization page', () => {
    cy.interceptAdminAPI('GET', 'organizations', { organizations: [] })
    cy.interceptAdminAPI('GET', 'organizations/archived', { organizations: [] })

    cy.visit('/customers')
    cy.get('#empty-state').find('a').contains('Add Organization').click()
    cy.url().should('include', '/customers/new')
  })

  it('creates a new organization with owner user', () => {
    cy.interceptAdminAPI('GET', 'organizations', { organizations: [] })
    cy.interceptAdminAPI('GET', 'organizations/archived', { organizations: [] })

    cy.intercept('POST', 'http://localhost:8000/api/v1/admin/organizations', {
      statusCode: 200,
      body: { id: 'org-new', name: 'NewCo', domain: 'newco.com' },
    }).as('createOrg')

    cy.intercept('POST', 'http://localhost:8000/api/v1/admin/organizations/org-new/users', {
      statusCode: 200,
      body: { user_id: 'user-new', email: 'owner@newco.com' },
    }).as('createUser')

    cy.visit('/customers/new')
    cy.get('#organization-name').type('NewCo')
    cy.get('#contact-name').type('Owner Name')
    cy.get('#contact-email').type('owner@newco.com')
    cy.get('#submit-btn').click()
    cy.wait('@createOrg')
    cy.wait('@createUser')
    cy.url().should('include', '/customers/org-new')
  })

  it('archives an organization via confirmation modal', () => {
    cy.fixture('organizations.json').then((data) => {
      cy.interceptAdminAPI('GET', 'organizations', data)
      cy.interceptAdminAPI('GET', 'organizations/archived', { organizations: [] })
    })

    cy.intercept('DELETE', 'http://localhost:8000/api/v1/admin/organizations/org-1', {
      statusCode: 200,
      body: {},
    }).as('archiveOrg')

    cy.visit('/customers')
    cy.get('#archive-btn-org-1').click()
    cy.get('#archive-modal').should('be.visible')
    cy.get('#archive-modal-title').should('contain', 'Archive Organization')
    cy.get('#archive-modal-confirm').click()
    cy.wait('@archiveOrg')
    cy.get('#archive-modal').should('not.exist')
  })

  it('filters organizations by search query', () => {
    cy.fixture('organizations.json').then((data) => {
      cy.interceptAdminAPI('GET', 'organizations', data)
      cy.interceptAdminAPI('GET', 'organizations/archived', { organizations: [] })
    })

    cy.visit('/customers')
    cy.get('#search-input').type('Acme')
    cy.get('[id^="organization-card-"]').should('have.length', 1)
    cy.contains('Acme Corp').should('be.visible')
    cy.contains('Globex Inc').should('not.exist')
  })
})
