FROM python:3.11-slim
WORKDIR /srv
COPY contracts /srv/contracts
RUN pip install --no-cache-dir /srv/contracts uvicorn
COPY services/auditor/requirements.in /srv/requirements.in
RUN pip install --no-cache-dir -r /srv/requirements.in
COPY services/auditor /srv/service
COPY config /srv/config
COPY configs /srv/configs
WORKDIR /srv/service
ENV BIFLOW_MOCK=1 DATA_DIR=/data
EXPOSE 8102
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8102"]
