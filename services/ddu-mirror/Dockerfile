FROM python:3.11-slim
WORKDIR /app

COPY libs/ddu-py-common /opt/ddu-py-common
RUN pip install --no-cache-dir /opt/ddu-py-common
COPY services/ddu-mirror /app
RUN pip install --no-cache-dir /app

ENV PORT=8130
EXPOSE 8130
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8130"]
