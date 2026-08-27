FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY apps apps
COPY domain domain
COPY trading trading
COPY research research
COPY intelligence intelligence
COPY storage storage
COPY platform_core platform_core
COPY scripts scripts
RUN pip install --upgrade pip && pip install '.[research,intelligence]'
CMD ["python", "-m", "apps.trader.main"]
