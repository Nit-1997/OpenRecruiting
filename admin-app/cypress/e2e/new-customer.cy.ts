describe("New Customer Page", () => {
  beforeEach(() => {
    cy.loginAsAdmin();
  });

  it("renders the new organization form", () => {
    cy.visit("/customers/new");
    cy.get("#new-organization-page").should("be.visible");
    cy.get("#new-organization-form").should("be.visible");
    cy.get("#organization-name").should("be.visible");
    cy.get("#contact-name").should("be.visible");
    cy.get("#contact-email").should("be.visible");
  });

  it("creates organization with owner", () => {
    cy.intercept("POST", "http://localhost:8000/api/v1/admin/organizations", {
      statusCode: 200,
      body: { id: "org-new", name: "NewCo", domain: "newco.com" },
    }).as("createOrg");

    cy.visit("/customers/new");
    cy.get("#organization-name").type("NewCo");
    cy.get("#contact-name").type("Jane Smith");
    cy.get("#contact-email").type("jane@newco.com");
    cy.get("#submit-btn").click();
    cy.wait("@createOrg");
  });

  it("submit button is disabled when fields are empty", () => {
    cy.visit("/customers/new");
    cy.get("#submit-btn").should("be.disabled");
  });

  it("shows error on duplicate domain", () => {
    cy.intercept("POST", "http://localhost:8000/api/v1/admin/organizations", {
      statusCode: 409,
      body: { detail: "Organization with this domain already exists" },
    }).as("duplicateOrg");

    cy.visit("/customers/new");
    cy.get("#organization-name").type("ExistingCo");
    cy.get("#contact-name").type("John Doe");
    cy.get("#contact-email").type("john@existing.com");
    cy.get("#submit-btn").click();
    cy.wait("@duplicateOrg");
    cy.get("#error-message").should("be.visible");
  });

  it("cancel navigates back", () => {
    cy.interceptAdminAPI("GET", "organizations", []);
    cy.visit("/customers/new");
    cy.get("#cancel-btn").click();
    cy.url().should("include", "/customers");
  });
});
