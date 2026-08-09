# Backend image. Build with the REPO ROOT as context so intake-core and llm-core
# are available without a staging script:
#   docker build -f backend/Dockerfile -t openrecruiting-backend .
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# intake-core is a sibling source package shared with the voice agent. Install it
# from the working tree so backend imports resolve to this checkout, never to a
# stale published copy.
COPY intake-core /tmp/intake-core
RUN pip install --no-cache-dir /tmp/intake-core && rm -rf /tmp/intake-core

# llm-core is the shared gateway client. Installed the same way and for the same
# reason as intake-core. Nothing imports it yet — it lands here first so the
# migration phases start with `import llm_core` already resolving inside the
# image, rather than discovering on their first build that the package they were
# written against was never installed.
COPY llm-core /tmp/llm-core
RUN pip install --no-cache-dir /tmp/llm-core && rm -rf /tmp/llm-core

COPY backend/ /app/

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
