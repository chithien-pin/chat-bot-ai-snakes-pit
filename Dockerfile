# CPS Bot — Python backend (Telegram, Lark, Dashboard API, sync jobs)
FROM python:3.12-slim-bookworm

WORKDIR /app

# lxml + build deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py .
COPY cps_bot/ ./cps_bot/
COPY dashboard/ ./dashboard/
COPY dashboard_api.py bot.py lark_bot.py menu_category_sync.py category_attributes_sync.py ./

COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.py /app/docker/healthcheck.py
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python /app/docker/healthcheck.py

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dashboard"]
