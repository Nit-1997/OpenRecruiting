import pytest
from app.integrations.ats.passthrough.ashby.candidates import AshbyCandidatesAdapter


class _FakeTransport:
    def __init__(self, responses): self._responses = responses; self.calls = []
    async def passthrough(self, integration_id, method, path, body=None):
        self.calls.append((path, body))
        return self._responses[path]


@pytest.mark.asyncio
async def test_get_application_resolves_resume_via_candidate_then_file_info():
    t = _FakeTransport({
        "/candidate.info": {"results": {"name": "Jenna Jacobs",
            "emailAddresses": [{"value": "j@example.com"}],
            "resumeFileHandle": {"name": "r.pdf", "handle": "HANDLE-STR"}}},
        "/file.info": {"results": {"url": "https://s3/r.pdf"}},
        "/application.info": {"results": {"status": "ACTIVE", "info": {"jobId": "job-1"}}},
    })
    adapter = AshbyCandidatesAdapter(t, "iid-1")
    app = await adapter.get_application("app-1", "cand-1")

    assert app.attachments[0].type == "RESUME"
    assert app.attachments[0].url == "https://s3/r.pdf"
    assert app.candidate.position is None  # absent in fixture, no crash
    # file.info must be called with the HANDLE STRING, not the object/id
    file_call = next(c for c in t.calls if c[0] == "/file.info")
    assert file_call[1] == {"fileHandle": "HANDLE-STR"}


@pytest.mark.asyncio
async def test_get_application_no_resume_handle_yields_no_attachment():
    t = _FakeTransport({
        "/candidate.info": {"results": {"name": "No Resume", "emailAddresses": [{"value": "n@example.com"}]}},
        "/application.info": {"results": {"status": "REJECTED"}},
    })
    adapter = AshbyCandidatesAdapter(t, "iid-1")
    app = await adapter.get_application("app-1", "cand-1")
    assert app.attachments == []
    assert app.status == "REJECTED"
