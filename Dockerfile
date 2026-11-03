# CPU 版镜像：模型在首次启动时下载到挂载卷里
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    HF_HOME=/data/hf_cache \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# 部分依赖需要编译（chromadb / tokenizers / jieba）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 8501
CMD ["python", "-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]

