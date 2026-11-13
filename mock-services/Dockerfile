# The three simulated applications (Slack, Google Workspace, payroll). One image; the
# service to run is chosen by the command in docker-compose.yml. Data lives in memory.
FROM python:3.13-slim
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN useradd --system --uid 10002 --home-dir /app mock
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY mockservices ./mockservices
USER mock
CMD ["uvicorn", "mockservices.slack:app", "--host", "0.0.0.0", "--port", "9101"]
