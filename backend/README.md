# OpenRecruiting Backend

Standalone FastAPI service hosting the v2 (layered architecture) API. Endpoints are progressively absorbed from v1; once parity is reached, v1 will be decommissioned.

Spec: [`docs/superpowers/specs/2026-05-18-roles-detail-v2-api-design.md`](../../docs/superpowers/specs/2026-05-18-roles-detail-v2-api-design.md)

## Run locally

```bash
cd backend/v2
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8004
```

## Tests

```bash
pip install -r requirements-test.txt
pytest tests/ -v
```

For legacy endpoints not yet migrated, see [`backend/v1/`](../v1/).
