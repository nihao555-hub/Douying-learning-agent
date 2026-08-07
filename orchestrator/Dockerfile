# 编排服务 Docker 镜像
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 确保数据目录存在
RUN mkdir -p /app/data/videos /app/data/audios /app/data/transcripts

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "main.py"]
