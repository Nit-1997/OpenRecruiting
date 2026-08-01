# Backend image. Build with the REPO ROOT as context so intake-core is available
# without a staging script:
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

COPY backend/ /app/

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
