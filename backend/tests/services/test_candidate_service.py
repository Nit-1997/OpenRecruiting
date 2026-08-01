import pytest
from app.services.candidate_service import CandidateService, get_candidate_service


def test_get_candidate_service_returns_instance():
    svc = get_candidate_service()
    assert isinstance(svc, CandidateService)
    assert hasattr(svc, "add_candidate")
