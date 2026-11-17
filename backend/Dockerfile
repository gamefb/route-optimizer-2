FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MAP_DATA_DIR=/data
WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

VOLUME /data
EXPOSE 8000
# One worker on purpose: the loaded map lives in this process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
