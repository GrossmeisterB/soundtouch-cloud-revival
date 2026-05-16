FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY templates /app/templates
COPY static /app/static

ENV PYTHONUNBUFFERED=1
ENV LISTEN_PORT=8181

EXPOSE 8181

HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8181/healthz || exit 1

CMD ["python", "app.py"]
