describe('Customer Detail Page', () => {
  const orgId = 'org-1'

  beforeEach(() => {
    cy.loginAsAdmin()

    cy.interceptAdminAPI('GET', `organizations/${orgId}`, {
      id: orgId,
      name: 'Acme Corp',
      domain: 'acme.com',
      description: 'Technology company',
      created_at: '2024-06-01T00:00:00Z',
      updated_at: '2024-06-15T00:00:00Z',
    })

    cy.fixture('users.json').then((data) => {
      const active = data.users.filter((u: { deleted_at: string | null }) => !u.deleted_at)
      const deleted = data.users.filter((u: { deleted_at: string | null }) => u.deleted_at)
      cy.interceptAdminAPI('GET', `organizations/${orgId}/users`, { users: active })
      cy.interceptAdminAPI('GET', `organizations/${orgId}/users/deleted`, { users: deleted })
    })

    cy.fixture('requisitions.json').then((data) => {
      cy.interceptAdminAPI('GET', `requisitions/organizations/${orgId}`, data)
      cy.interceptAdminAPI('GET', `requisitions/organizations/${orgId}/deleted`, { requisitions: [] })
    })
  })

  it('displays the organization info in the sidebar', () => {
    cy.visit(`/customers/${orgId}`)
    cy.get('#organization-detail-page').should('be.visible')
    cy.get('#org-detail-title').should('contain', 'Acme Corp')
    cy.get('#org-detail-sidebar').should('be.visible')
    cy.get('#org-detail-name').should('contain', 'Acme Corp')
    cy.get('#org-detail-domain').should('contain', 'acme.com')
  })

  it('shows active users in the users tab', () => {
    cy.visit(`/customers/${orgId}`)
    cy.get('#org-tab-users').should('have.class', 'border-primary')
    cy.get('#org-users-table').should('be.visible')
    cy.get('[id^="org-user-row-"]').should('have.length', 2)
    cy.contains('Alice Johnson').should('be.visible')
    cy.contains('Bob Smith').should('be.visible')
  })

  it('adds a user to the organization', () => {
    cy.intercept('POST', `http://localhost:8000/api/v1/admin/organizations/${orgId}/users`, {
      statusCode: 200,
      body: { user_id: 'user-new', email: 'new@acme.com' },
    }).as('addUser')

    cy.visit(`/customers/${orgId}`)
    cy.get('#org-add-user-btn').click()
    cy.get('#org-add-user-form').should('be.visible')
    cy.get('#org-new-user-name').type('New User')
    cy.get('#org-new-user-email').type('new@acme.com')
    cy.get('#org-submit-add-user').click()
    cy.wait('@addUser')
    cy.get('#org-add-user-form').should('not.exist')
  })

  it('deletes a user from the organization', () => {
    cy.intercept('DELETE', 'http://localhost:8000/api/v1/admin/users/user-1', {
      statusCode: 200,
      body: {},
    }).as('deleteUser')

    cy.visit(`/customers/${orgId}`)
    cy.get('#org-user-delete-btn-user-1').click()
    cy.get('#org-user-confirm-delete-user-1').click()
    cy.wait('@deleteUser')
  })

  it('displays requisitions in the requisitions tab', () => {
    cy.visit(`/customers/${orgId}`)
    cy.get('#org-tab-requisitions').click()
    cy.get('#org-requisitions-section').should('be.visible')
    cy.get('#org-requisitions-list').should('be.visible')
    cy.contains('Senior Frontend Engineer').should('be.visible')
    cy.contains('Backend Engineer').should('be.visible')
  })
})
