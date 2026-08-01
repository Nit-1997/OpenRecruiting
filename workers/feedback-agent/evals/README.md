# Evals

The scoring pipeline was developed against recorded interviews: a fixture
captures a real round's transcript, questions and role context, the pipeline is
replayed against it, and the output is diffed run-to-run to catch regressions.

**The fixtures and recorded runs are not in this repository.** They were captured
from production interviews and contain real candidates' and interviewers' names,
what they said, and the hiring verdict reached about them. That is not data to
publish, redacted or otherwise, so it was removed before open-sourcing.

The tooling is still here:

| Script | Purpose |
|---|---|
| `../scripts/normalize_fixture.py` | Turn a captured round into a fixture (handles the name-redaction map) |
| `../scripts/replay.py` | Replay the pipeline against a fixture into `runs/` |
| `../scripts/diff_runs.py` | Diff two runs to spot a regression |

## Capturing your own

Fixtures live in `fixtures/` and runs in `runs/`; both are git-ignored, so
anything you capture from your own instance stays local. `normalize_fixture.py`
expects a round id and writes the fixture; see
`../tests/test_fixture_schema.py` for the shape it must satisfy.

If you contribute a fixture, synthesise it. Do not upload a real interview.
