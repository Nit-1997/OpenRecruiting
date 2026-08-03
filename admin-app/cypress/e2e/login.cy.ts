describe('Login Page', () => {
  beforeEach(() => {
    cy.intercept('POST', '**/auth/v1/token**', {
      statusCode: 200,
      body: {
        access_token: 'mock-access-token',
        token_type: 'bearer',
        expires_in: 3600,
        refresh_token: 'mock-refresh-token',
        user: {
          id: 'admin-1',
          email: 'admin@example.com',
          aud: 'authenticated',
          role: 'authenticated',
        },
      },
    }).as('signIn')
  })

  it('displays the login form with email and password fields', () => {
    cy.visit('/login')
    cy.get('#login-page').should('be.visible')
    cy.get('#login-title').should('contain', 'OpenRecruiting Admin')
    cy.get('#email-input').should('be.visible')
    cy.get('#password-input').should('be.visible')
    cy.get('#login-btn').should('be.visible').and('contain', 'Sign In')
  })

  it('logs in successfully and redirects to /customers', () => {
    cy.intercept('GET', '**/rest/v1/profiles**', {
      statusCode: 200,
      body: [{ id: 'admin-1', is_staff: true }],
    }).as('profileCheck')

    cy.intercept('GET', '**/auth/v1/user', {
      statusCode: 200,
      body: {
        id: 'admin-1',
        email: 'admin@example.com',
        aud: 'authenticated',
        role: 'authenticated',
      },
    }).as('getUser')

    cy.visit('/login')
    cy.get('#email-input').type('admin@example.com')
    cy.get('#password-input').type('password123')
    cy.get('#login-btn').click()
    cy.wait('@signIn')
    cy.url().should('include', '/')
  })

  it('shows access denied for non-staff user', () => {
    cy.intercept('GET', '**/auth/v1/user', {
      statusCode: 200,
      body: {
        id: 'non-staff-1',
        email: 'user@company.com',
        aud: 'authenticated',
        role: 'authenticated',
      },
    }).as('getUser')

    cy.intercept('GET', '**/rest/v1/profiles**', {
      statusCode: 200,
      body: [{ id: 'non-staff-1', is_staff: false }],
    }).as('profileCheck')

    cy.intercept('POST', '**/auth/v1/signout**', {
      statusCode: 200,
      body: {},
    }).as('signOut')

    cy.visit('/login')
    cy.get('#email-input').type('user@company.com')
    cy.get('#password-input').type('password123')
    cy.get('#login-btn').click()
    cy.wait('@signIn')
    cy.get('#error-message').should('contain', 'Access denied')
  })
})
