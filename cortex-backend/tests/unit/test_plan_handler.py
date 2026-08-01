import pytest

from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_plan_creates_has_round_edges(plan_handler):
    payload = load_fixture("plan_packet_senior_swe.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    has_round = [t for t in triplets if t.relation == "HAS_ROUND"]
    assert len(has_round) == 3
    round_names = [t.target_name for t in has_round]
    assert "Phone Screen" in round_names
    assert "Coding Round" in round_names
    assert "System Design" in round_names


@pytest.mark.asyncio
async def test_plan_creates_round_assesses_skill(plan_handler):
    payload = load_fixture("plan_packet_senior_swe.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    assesses_skill = [t for t in triplets if t.relation == "ASSESSES" and t.target_type == "Skill"]
    skill_names = [t.target_name for t in assesses_skill]
    assert "Python" in skill_names
    assert "algorithms" in skill_names
    assert "system design" in skill_names
    assert "distributed systems" in skill_names


@pytest.mark.asyncio
async def test_plan_creates_round_assesses_competency(plan_handler):
    payload = load_fixture("plan_packet_senior_swe.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    assesses_comp = [t for t in triplets if t.relation == "ASSESSES" and t.target_type == "Competency"]
    headings = [t.target_name for t in assesses_comp]
    assert "Communication" in headings
    assert "Problem Solving" in headings
    assert "System Thinking" in headings


@pytest.mark.asyncio
async def test_plan_creates_located_in(plan_handler):
    payload = load_fixture("plan_packet_senior_swe.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    located = [t for t in triplets if t.relation == "LOCATED_IN"]
    assert len(located) == 1
    assert located[0].target_name == "Bangalore"


@pytest.mark.asyncio
async def test_plan_creates_requires_edges(plan_handler):
    payload = load_fixture("plan_packet_senior_swe.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    requires = [t for t in triplets if t.relation == "REQUIRES"]
    assert len(requires) == 2
    skill_names = [t.target_name for t in requires]
    assert "Python" in skill_names
    assert "System Design" in skill_names


@pytest.mark.asyncio
async def test_plan_creates_nice_to_have(plan_handler):
    payload = load_fixture("plan_packet_senior_swe.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    nth = [t for t in triplets if t.relation == "NICE_TO_HAVE"]
    assert len(nth) == 1
    assert nth[0].target_name == "Kubernetes"


@pytest.mark.asyncio
async def test_empty_skills_no_assesses_skill_edges(plan_handler):
    payload = load_fixture("plan_packet_empty_skills.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    assesses_skill = [t for t in triplets if t.relation == "ASSESSES" and t.target_type == "Skill"]
    assert len(assesses_skill) == 0


@pytest.mark.asyncio
async def test_remote_location_type(plan_handler):
    payload = load_fixture("plan_packet_empty_skills.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    located = [t for t in triplets if t.relation == "LOCATED_IN"]
    assert len(located) == 1
    assert located[0].target_attributes["location_type"] == "remote"


@pytest.mark.asyncio
async def test_has_round_order_preserved(plan_handler):
    payload = load_fixture("plan_packet_senior_swe.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    has_round = [t for t in triplets if t.relation == "HAS_ROUND"]
    orders = [t.edge_attributes["order"] for t in has_round]
    assert orders == [0, 1, 2]


@pytest.mark.asyncio
async def test_plan_emits_organization_hosts_requisition(plan_handler):
    payload = load_fixture("plan_packet_senior_swe.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    hosts = [t for t in triplets if t.relation == "HOSTS"]
    assert len(hosts) == 1
    edge = hosts[0]
    assert edge.source_type == "Organization"
    assert edge.source_name == "Acme Corp"
    assert edge.source_id == "org-001"
    assert edge.source_attributes["domain"] == "acme.com"
    assert edge.target_type == "Requisition"
    assert edge.target_name == "Senior Backend Engineer"
    assert edge.target_id == "req-001"


@pytest.mark.asyncio
async def test_plan_skips_hosts_when_org_name_missing(plan_handler):
    payload = load_fixture("plan_packet_empty_skills.json")
    triplets = plan_handler.build_triplets_from_payload(payload, "org-001")

    hosts = [t for t in triplets if t.relation == "HOSTS"]
    assert len(hosts) == 0
