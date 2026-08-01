# Intake worker. Build with the REPO ROOT as context:
#   docker build -f workers/intake-agent/Dockerfile -t openrecruiting-intake-agent .
FROM python:3.11-slim

WORKDIR /app

COPY workers/intake-agent/production/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi "uvicorn[standard]"

COPY workers/intake-agent/src/ src/
COPY workers/intake-agent/production/ production/
COPY workers/intake-agent/app.py .

EXPOSE 9002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9002"]
