FROM python:3.11-slim
# uv (fast installer) from PyPI, not ghcr.io: one registry fewer, works on networks that block ghcr.io
RUN pip install --no-cache-dir uv==0.13.6
WORKDIR /srv
COPY services/dashboard/requirements.lock /srv/requirements.lock
RUN UV_HTTP_TIMEOUT=300 uv pip install --system --no-cache -r /srv/requirements.lock
COPY services/dashboard /srv/service
WORKDIR /srv/service
ENV DATA_DIR=/srv/data GATEWAY_URL=http://gateway:8000 PYTHONUNBUFFERED=1
EXPOSE 8501
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
