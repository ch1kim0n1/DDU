FROM python:3.11-slim AS base
WORKDIR /app

COPY libs/ddu-py-common /opt/ddu-py-common
RUN pip install --no-cache-dir /opt/ddu-py-common

COPY services/ddu-intel /app
RUN pip install --no-cache-dir /app

ENV PORT=8112 MODEL_MODE=stub
EXPOSE 8112
CMD ["python", "app.py"]
