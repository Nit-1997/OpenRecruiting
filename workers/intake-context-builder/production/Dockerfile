# Built with the REPO ROOT as context so the shared packages are visible:
#   docker build -f workers/intake-context-builder/production/Dockerfile .
# deploy/ecr-push.sh does this. It previously built from workers/intake-context-builder/,
# which could not see intake-core or llm-core at the repo root.
FROM public.ecr.aws/lambda/python:3.11

COPY workers/intake-context-builder/requirements.txt .
RUN pip install -r requirements.txt

# Shared packages, installed from the working tree so they match this checkout —
# the same treatment the compose Dockerfile gives them. This replaces a
# `COPY intake-core-pkg/` of a directory that does not exist in the tree and is
# gitignored, i.e. this deploy path could not previously be built from a clean
# checkout at all.
COPY intake-core /tmp/intake-core
RUN pip install --no-cache-dir /tmp/intake-core && rm -rf /tmp/intake-core

# llm-core is the gateway client. parse_jd and synthesize moved onto it in phase
# 4, and handler.py closes it per invocation because this runtime creates and
# destroys an event loop for every call.
COPY llm-core /tmp/llm-core
RUN pip install --no-cache-dir /tmp/llm-core && rm -rf /tmp/llm-core

COPY workers/intake-context-builder/src/ ${LAMBDA_TASK_ROOT}/src/
COPY workers/intake-context-builder/production/ ${LAMBDA_TASK_ROOT}/production/

CMD ["production.handler.handler"]
