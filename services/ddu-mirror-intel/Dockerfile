FROM python:3.14-slim-bookworm AS base
WORKDIR /app

RUN useradd -m -u 10001 mirror

COPY libs/ddu-py-common /opt/ddu-py-common
RUN pip install --no-cache-dir /opt/ddu-py-common

COPY services/ddu-mirror-intel /app
RUN pip install --no-cache-dir "/app[llm,discovery]" \
    && chown -R mirror:mirror /app

ENV MIRROR_INTEL_PORT=8120
EXPOSE 8120
USER mirror

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8120/healthz')"

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8120"]
