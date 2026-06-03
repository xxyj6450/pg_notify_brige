FROM docker.m.daocloud.io/library/python:3.12.1-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
# 替换Debian apt源为阿里云镜像
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list || true
WORKDIR /app
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip \
    && pip install -r requirements.txt  \
    && pip install --no-deps -e .

RUN useradd --create-home --shell /bin/bash appuser
USER appuser

CMD ["python", "-m", "pg_notify_bridge"]
