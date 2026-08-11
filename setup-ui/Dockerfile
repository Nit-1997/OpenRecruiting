FROM python:3.11-slim

WORKDIR /srv

COPY setup-ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY setup-ui/app /srv/app

# 3010 is bound to 127.0.0.1 by docker-compose.yml, NOT published on 0.0.0.0.
# This service can edit every secret in the deployment and restart containers,
# so it must not be reachable from a network by default. Remote operators use an
# SSH tunnel; see docs.
EXPOSE 3010

ENV PYTHONUNBUFFERED=1
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:3010/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3010"]
