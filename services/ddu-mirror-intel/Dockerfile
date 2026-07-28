FROM python:3.11-slim AS base
WORKDIR /app

# Install the shared DDU service contract library first.
COPY libs/ddu-py-common /opt/ddu-py-common
RUN pip install --no-cache-dir /opt/ddu-py-common

COPY services/ddu-mirror-intel /app
# Production includes the live LLM and Sherlock adapters. Runtime readiness
# policy still controls whether an unavailable vendor may use labelled cache
# data or must fail closed.
RUN pip install --no-cache-dir "/app[llm,discovery]"

ENV MIRROR_INTEL_PORT=8120
EXPOSE 8120
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8120"]
