FROM python:3.11-slim AS base
WORKDIR /app

# Install ddu-py-common from the libs directory.
COPY libs/ddu-py-common /opt/ddu-py-common
RUN pip install --no-cache-dir /opt/ddu-py-common

COPY services/ddu-mirror-intel /app
RUN pip install --no-cache-dir /app

# `anthropic` and `sherlock-project` are deliberately NOT installed here.
# The service is fully functional without them — it falls back to a
# deterministic LLM provider and cached discovery results, and discloses both
# in its responses. Add them with `pip install /app[llm,discovery]` when the
# demo has credentials.

ENV MIRROR_INTEL_PORT=8120
EXPOSE 8120
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8120"]
