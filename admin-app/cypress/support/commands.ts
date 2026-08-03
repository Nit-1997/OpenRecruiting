declare namespace Cypress {
  interface Chainable {
    loginAsAdmin(): Chainable<void>
    interceptAdminAPI(
      method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
      path: string,
      response: object | object[]
    ): Chainable<void>
  }
}

const MOCK_USER = {
  id: 'admin-1',
  email: 'admin@example.com',
  aud: 'authenticated',
  role: 'authenticated',
  app_metadata: {},
  user_metadata: { full_name: 'Test Admin' },
  created_at: '2024-01-01T00:00:00Z',
}

const MOCK_SESSION = {
  access_token: 'mock-access-token',
  token_type: 'bearer',
  expires_in: 3600,
  expires_at: Math.floor(Date.now() / 1000) + 3600,
  refresh_token: 'mock-refresh-token',
  user: MOCK_USER,
}

const MOCK_PROFILE = {
  id: 'admin-1',
  is_staff: true,
  email: 'admin@example.com',
  full_name: 'Test Admin',
}

Cypress.Commands.add('loginAsAdmin', () => {
  cy.session('admin', () => {
    cy.intercept('POST', '**/auth/v1/token**', {
      statusCode: 200,
      body: MOCK_SESSION,
    }).as('signIn')

    cy.intercept('GET', '**/auth/v1/user', {
      statusCode: 200,
      body: MOCK_USER,
    }).as('getUser')

    cy.intercept('GET', '**/rest/v1/profiles**', {
      statusCode: 200,
      body: MOCK_PROFILE,
    }).as('profiles')

    cy.intercept('GET', 'http://localhost:8000/api/v1/admin/**', {
      statusCode: 200,
      body: {},
    })

    cy.visit('/login')
    cy.get('#email-input').type('admin@example.com')
    cy.get('#password-input').type('password123')
    cy.get('#login-btn').click()
    cy.wait('@signIn')
    cy.url({ timeout: 10000 }).should('not.include', '/login')
  })

  cy.intercept('GET', '**/auth/v1/user', {
    statusCode: 200,
    body: MOCK_USER,
  }).as('authUser')

  cy.intercept('POST', '**/auth/v1/token**', {
    statusCode: 200,
    body: MOCK_SESSION,
  }).as('authToken')

  cy.intercept('GET', '**/rest/v1/profiles**', {
    statusCode: 200,
    body: MOCK_PROFILE,
  }).as('profiles')

  cy.intercept('POST', '**/auth/v1/signout**', {
    statusCode: 200,
    body: {},
  }).as('signOut')

  cy.intercept('GET', '**/auth/v1/session', {
    statusCode: 200,
    body: MOCK_SESSION,
  }).as('authSession')
})

Cypress.Commands.add(
  'interceptAdminAPI',
  (method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, response: object | object[]) => {
    cy.intercept(method, `http://localhost:8000/api/v1/admin/${path}`, {
      statusCode: 200,
      body: response,
    })
  }
)
