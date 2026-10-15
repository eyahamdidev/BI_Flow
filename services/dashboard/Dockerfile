FROM python:3.11-slim
WORKDIR /srv
COPY services/dashboard/requirements.in /srv/requirements.in
RUN pip install --no-cache-dir -r /srv/requirements.in
COPY services/dashboard /srv/service
WORKDIR /srv/service
ENV DATA_DIR=/data GATEWAY_URL=http://gateway:8000
EXPOSE 8501
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
