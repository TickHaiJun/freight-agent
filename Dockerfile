FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 保守安装编译依赖，避免少数 Python 包在 slim 镜像中缺构建环境
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

COPY . /app

# 这些目录会被宿主机卷覆盖，但镜像内先建好能减少首次启动异常
RUN mkdir -p /app/runtime/logs /app/data/docs /app/data/chroma /app/data/cache /app/data/exports

EXPOSE 8012

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8012"]
