# The community API as a container: Cloud Run, Fly.io, Render, Railway or any server with Docker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    TRUST_PROXY=true

WORKDIR /app
COPY pyproject.toml README.md ./
COPY hellotas_api ./hellotas_api
# Building behind a network that inspects TLS (some university and company networks do)? Pass its certificate:
#   docker build --secret id=ca,src=/path/to/proxy-ca.crt .
# Without the secret, the build uses the normal public certificates.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install . && useradd --create-home --uid 10001 api

USER api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)"
# PORT is set by Cloud Run and most hosts; 8000 otherwise
CMD ["sh", "-c", "exec hellotas-api serve --host 0.0.0.0 --port ${PORT}"]
