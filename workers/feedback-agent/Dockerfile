# Feedback worker. Build with the REPO ROOT as context:
#   docker build -f workers/feedback-agent/Dockerfile -t openrecruiting-feedback-agent .
#
# Heads up: this installs torch (CPU) and sentence-transformers for the semantic
# similarity step, so the image is a few GB and the first build is slow.
FROM python:3.11-slim

WORKDIR /app

# The Lambda production pins, not the dev requirements.
COPY workers/feedback-agent/production/requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt \
    && pip install --no-cache-dir "uvicorn[standard]"

COPY workers/feedback-agent/src/ src/
COPY workers/feedback-agent/production/ production/
COPY workers/feedback-agent/app.py .

EXPOSE 9001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9001"]
