describe("Requisition Create Page", () => {
  const customerId = "org-1";
  const mockCustomer = {
    id: customerId,
    name: "Acme Corp",
    domain: "acme.com",
    requisitionCount: 0,
  };

  beforeEach(() => {
    cy.loginAsAdmin();

    cy.interceptAdminAPI("GET", `organizations/${customerId}`, mockCustomer);

    cy.window().then((win) => {
      win.localStorage.setItem("admin_customers", JSON.stringify([mockCustomer]));
    });
  });

  it("renders the new requisition form for customer", () => {
    cy.visit(`/requisitions/new/${customerId}`);
    cy.get("#new-requisition-page").should("be.visible");
    cy.get("#basic-info-step").should("be.visible");
    cy.get("#role-title-input").should("be.visible");
    cy.get("#level-select").should("be.visible");
    cy.get("#location-input").should("be.visible");
  });

  it("navigates through multi-step form", () => {
    cy.visit(`/requisitions/new/${customerId}`);
    cy.get("#role-title-input").type("Data Engineer");
    cy.get("#location-input").type("Remote");
    cy.get("#next-btn-basic").click();
    cy.get("#intake-notes-step").should("be.visible");
    cy.get("#jd-textarea").should("be.visible");
  });

  it("validates required fields on basic info", () => {
    cy.visit(`/requisitions/new/${customerId}`);
    cy.get("#next-btn-basic").should("be.visible");
    cy.get("#role-title-input").should("have.value", "");
  });

  it("shows back link to customer page", () => {
    cy.visit(`/requisitions/new/${customerId}`);
    cy.get("#back-to-customer").should("be.visible");
    cy.get("#back-to-customer").should("have.attr", "href").and("include", customerId);
  });
});
