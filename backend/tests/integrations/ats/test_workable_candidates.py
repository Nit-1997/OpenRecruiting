import pytest
from app.integrations.ats.passthrough.workable.candidates import WorkableCandidatesAdapter


class _FakeTransport:
    def __init__(self, responses): self._responses = responses; self.calls = []
    async def passthrough(self, integration_id, method, path, body=None):
        self.calls.append((method, path)); return self._responses[path]


@pytest.mark.asyncio
async def test_get_application_pulls_candidate_with_resume():
    t = _FakeTransport({"/candidates/c1": {"candidate": {
        "id": "c1", "firstname": "Elvie", "lastname": "Schmidt",
        "email": "e@example.com", "resume_url": "https://wk/r.pdf", "stage": "Phone Screen"}}})
    app = await WorkableCandidatesAdapter(t, "iid").get_application("c1", "c1")
    assert app.attachments[0].url == "https://wk/r.pdf"
    assert app.candidate.first_name == "Elvie"
    assert ("GET", "/candidates/c1") in t.calls
