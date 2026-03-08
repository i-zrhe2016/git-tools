FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GIT_API_DATA_DIR=/app/data \
    GIT_API_HOME=/app/data/home \
    GIT_API_WORKSPACE_ROOT=/workspace \
    GIT_API_DEFAULT_KEY_NAME=default

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY setup_git_ssh.sh push_git.sh README.md ./

RUN chmod +x /app/setup_git_ssh.sh /app/push_git.sh \
    && mkdir -p /app/data/keys /app/data/home /workspace

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
