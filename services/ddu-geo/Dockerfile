FROM python:3.11-slim AS base
WORKDIR /app

# Install ddu-py-common from the libs directory.
COPY libs/ddu-py-common /opt/ddu-py-common
RUN pip install --no-cache-dir /opt/ddu-py-common

COPY services/ddu-geo /app
RUN pip install --no-cache-dir /app

ENV PORT=8105
EXPOSE 8105
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8105"]
