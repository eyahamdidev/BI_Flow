FROM python:3.11-slim
# uv installs from the lockfile ~10x faster than pip
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
WORKDIR /srv

# 1) Third-party deps from the lockfile. This layer is cached until requirements.lock changes.
COPY services/etl/requirements.lock /srv/requirements.lock
RUN UV_HTTP_TIMEOUT=300 uv pip install --system --no-cache -r /srv/requirements.lock

# 2) Shared contracts package (its deps are already in the lock).
COPY contracts /srv/contracts
RUN uv pip install --system --no-cache --no-deps /srv/contracts

# 3) Service code and configs last: editing code only rebuilds from here.
COPY config /srv/config
COPY configs /srv/configs
COPY services/etl /srv/service
WORKDIR /srv/service
ENV BIFLOW_MOCK=1 DATA_DIR=/data BIFLOW_CONFIG_DIR=/srv/config PYTHONUNBUFFERED=1
EXPOSE 8101
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8101"]
