FROM python:3.11-slim
WORKDIR /srv
COPY contracts /srv/contracts
RUN pip install --no-cache-dir /srv/contracts uvicorn
COPY services/auditor/requirements.lock /srv/requirements.lock
RUN pip install --no-cache-dir -r /srv/requirements.lock
COPY services/auditor /srv/service
COPY prompts/auditor /srv/prompts/auditor
COPY config /srv/config
COPY configs /srv/configs
WORKDIR /srv/service
ENV BIFLOW_MOCK=1 DATA_DIR=/data BIFLOW_PROMPTS_DIR=/srv/prompts/auditor
EXPOSE 8102
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8102"]
