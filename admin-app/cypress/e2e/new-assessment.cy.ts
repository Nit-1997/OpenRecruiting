describe("New Assessment Template Page", () => {
  beforeEach(() => {
    cy.loginAsAdmin();
  });

  it("renders the new assessment form", () => {
    cy.visit("/assessments/new");
    cy.get("#new-assessment-page").should("be.visible");
    cy.get("#new-assessment-form").should("be.visible");
    cy.get("#task-json").should("exist");
    cy.get("#eval-json").should("exist");
  });

  it("creates assessment template with valid JSON", () => {
    const taskJson = JSON.stringify({
      scenario: { title: "System Design Challenge" },
      display: { title: "System Design Challenge", description: "Design a component library" },
      task_metadata: { seniority_level: "Senior", estimated_time: 60 },
    });
    const evalJson = JSON.stringify({
      title: "System Design Eval",
      seniority: "Senior",
      total_points: 100,
      pass_threshold: 60,
    });

    cy.intercept("POST", "http://localhost:8000/api/v1/admin/assessment-templates", {
      statusCode: 200,
      body: { id: "tmpl-new", title: "System Design Challenge" },
    }).as("createTemplate");

    cy.visit("/assessments/new");
    cy.get("#task-json").invoke("val", "").trigger("change");
    cy.get("#task-json").invoke("val", taskJson).trigger("change").trigger("input");
    cy.get("#eval-json").invoke("val", "").trigger("change");
    cy.get("#eval-json").invoke("val", evalJson).trigger("change").trigger("input");
    cy.get("#form-actions button[type='submit']").click();
    cy.wait("@createTemplate");
    cy.get("#success-message").should("be.visible");
  });

  it("shows inferred preview from JSON", () => {
    cy.visit("/assessments/new");
    cy.get("#inferred-preview").should("be.visible");
  });

  it("toggles tool checkboxes", () => {
    cy.visit("/assessments/new");
    cy.get("#tool-toggle-excalidraw").should("exist");
    cy.get("#tool-toggle-excalidraw").click({ force: true });
  });

  it("shows collapsible JSON sections", () => {
    cy.visit("/assessments/new");
    cy.get("#task-json-section").should("be.visible");
    cy.get("#eval-json-section").should("be.visible");
    cy.get("#task-json-section-toggle").click();
    cy.get("#task-json-section-content").should("not.exist");
  });
});
