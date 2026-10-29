FROM python:3.11-slim
# uv (fast installer) from PyPI, not ghcr.io: one registry fewer, works on networks that block ghcr.io
RUN pip install --no-cache-dir uv==0.13.6
WORKDIR /srv

# 1) Third-party deps from the lockfile. This layer is cached until requirements.lock changes.
COPY services/semantic_kpi/requirements.lock /srv/requirements.lock
RUN UV_HTTP_TIMEOUT=300 uv pip install --system --no-cache -r /srv/requirements.lock

# 2) Shared contracts package (its deps are already in the lock).
COPY contracts /srv/contracts
RUN uv pip install --system --no-cache --no-deps /srv/contracts

# 3) Service code and configs last: editing code only rebuilds from here.
COPY config /srv/config
COPY configs /srv/configs
COPY services/semantic_kpi /srv/service
WORKDIR /srv/service
ENV BIFLOW_MOCK=1 DATA_DIR=/srv/data BIFLOW_CONFIG_DIR=/srv/config PYTHONUNBUFFERED=1
EXPOSE 8105
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8105"]
