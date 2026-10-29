FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
WORKDIR /srv
COPY services/dashboard/requirements.lock /srv/requirements.lock
RUN UV_HTTP_TIMEOUT=300 uv pip install --system --no-cache -r /srv/requirements.lock
COPY services/dashboard /srv/service
WORKDIR /srv/service
ENV DATA_DIR=/data GATEWAY_URL=http://gateway:8000 PYTHONUNBUFFERED=1
EXPOSE 8501
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
