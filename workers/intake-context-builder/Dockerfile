# Intake context-builder worker. Build with the REPO ROOT as context -- this one
# needs the shared intake-core package:
#   docker build -f workers/intake-context-builder/Dockerfile -t openrecruiting-intake-context-builder .
FROM python:3.11-slim

WORKDIR /app

COPY workers/intake-context-builder/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi "uvicorn[standard]"

# Shared package, installed from the working tree so it matches this checkout.
COPY intake-core /tmp/intake-core
RUN pip install --no-cache-dir /tmp/intake-core && rm -rf /tmp/intake-core

COPY workers/intake-context-builder/src/ src/
COPY workers/intake-context-builder/production/ production/
COPY workers/intake-context-builder/app.py .

EXPOSE 9003

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9003"]
