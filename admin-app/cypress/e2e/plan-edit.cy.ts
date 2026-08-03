describe("Plan Edit Page", () => {
  const reqId = "req-1";

  const mockPlan = {
    rounds: [
      {
        id: "round-1",
        round_number: 1,
        name: "Technical Screen",
        description: "Initial technical assessment",
        round_type: "interview",
        duration_minutes: 45,
        skills: ["React", "TypeScript"],
        feedback_questions: [
          {
            id: "q-1",
            heading: "Problem Solving",
            description: "Assess problem solving ability",
            question_number: 1,
          },
        ],
        guidelines: [],
      },
      {
        id: "round-2",
        round_number: 2,
        name: "System Design",
        description: "Architecture discussion",
        round_type: "interview",
        duration_minutes: 60,
        skills: ["System Design"],
        feedback_questions: [],
        guidelines: [],
      },
    ],
  };

  beforeEach(() => {
    cy.loginAsAdmin();

    cy.fixture("requisitions.json").then((data) => {
      cy.interceptAdminAPI("GET", `requisitions/${reqId}`, data.requisitions[0]);
      cy.interceptAdminAPI("GET", `organizations/${data.requisitions[0].organization_id}`, {
        id: data.requisitions[0].organization_id,
        name: "Acme Corp",
      });
    });

    cy.interceptAdminAPI("GET", `requisitions/${reqId}/plan`, mockPlan);
  });

  it("loads existing plan with rounds in sidebar", () => {
    cy.visit(`/requisitions/${reqId}/plan/edit`);
    cy.get("#plan-edit-page").should("be.visible");
    cy.get("#rounds-sidebar").should("be.visible");
    cy.get("#rounds-list").should("be.visible");
    cy.get("#role-title").should("contain", "Senior Frontend Engineer");
  });

  it("displays round editor with questions", () => {
    cy.visit(`/requisitions/${reqId}/plan/edit`);
    cy.get("#round-editor").should("be.visible");
    cy.get("#round-heading").should("contain", "Technical Screen");
    cy.get("#questions-list").should("be.visible");
    cy.contains("Problem Solving").should("be.visible");
  });

  it("opens add round modal", () => {
    cy.visit(`/requisitions/${reqId}/plan/edit`);
    cy.get("#add-round-btn").click();
    cy.get("#add-round-modal").should("be.visible");
    cy.get("#select-interview-round").should("be.visible");
    cy.get("#select-assessment-round").should("be.visible");
  });

  it("saves plan via footer button", () => {
    cy.intercept("PUT", `http://localhost:8000/api/v1/admin/requisitions/${reqId}/plan`, {
      statusCode: 200,
      body: mockPlan,
    }).as("savePlan");

    cy.visit(`/requisitions/${reqId}/plan/edit`);
    cy.get("#save-all-footer-btn").click();
    cy.wait("@savePlan");
    cy.get("#toast-message").should("be.visible");
  });

  it("navigates between rounds via sidebar", () => {
    cy.visit(`/requisitions/${reqId}/plan/edit`);
    cy.get("#round-heading").should("contain", "Technical Screen");
    cy.get("#rounds-list").contains("System Design").click();
    cy.get("#round-heading").should("contain", "System Design");
  });
});
