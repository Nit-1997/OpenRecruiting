# Voice agent. Build with the REPO ROOT as context so intake-core is available:
#   docker build -f voice-agent/Dockerfile -t openrecruiting-voice-agent .
FROM python:3.11-slim

WORKDIR /app

# System deps for aiortc / cryptography + opencv (pulled in by
# pipecat.transports.smallwebrtc) — opencv needs X11/xcb libs at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    libopus-dev \
    libvpx-dev \
    libsrtp2-dev \
    libxcb1 \
    libxext6 \
    libsm6 \
    libxrender1 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY voice-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared package, installed from the working tree so it matches this checkout.
COPY intake-core /tmp/intake-core
RUN pip install --no-cache-dir /tmp/intake-core && rm -rf /tmp/intake-core

# llm-core is the shared gateway client. The intake coverage tracker moved onto
# it in phase 3, and phase 7 moved the pipecat LLM service too — src/pipeline/
# services.py now builds OpenAILLMService against the gateway's base_url, so
# nothing in this image holds a provider credential or a provider SDK.
# `pip install anthropic` must stay absent: requirements.txt deliberately drops
# pipecat's [anthropic] extra, which was the only thing installing it.
COPY llm-core /tmp/llm-core
RUN pip install --no-cache-dir /tmp/llm-core && rm -rf /tmp/llm-core

COPY voice-agent/src/ /app/src/

EXPOSE 8011

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8011"]
