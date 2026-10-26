FROM python:3.11-slim
WORKDIR /srv
COPY contracts /srv/contracts
RUN pip install --no-cache-dir /srv/contracts uvicorn
COPY services/profile_clean/requirements.in /srv/requirements.in
RUN pip install --no-cache-dir -r /srv/requirements.in
COPY services/profile_clean /srv/service
COPY config /srv/config
COPY configs /srv/configs
WORKDIR /srv/service
ENV BIFLOW_MOCK=0 FAKE_LLM=1 DATA_DIR=/data BIFLOW_CONFIG_DIR=/srv/config
EXPOSE 8103
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8103"]
