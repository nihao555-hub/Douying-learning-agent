#!/bin/bash

# 抖音博主学习 Agent v2 - 一键启动脚本
# 基于高 star 开源项目构建：Dify + Douyin_TikTok_Download_API

set -e

echo "=========================================="
echo "  抖音博主学习 Agent v2.0"
echo "  基于 Dify + Douyin_TikTok_Download_API"
echo "=========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ 错误: 未找到 Docker，请先安装 Docker 和 Docker Compose"
    echo "   安装参考: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查 docker compose 命令
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif docker-compose --version &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo "❌ 错误: 未找到 Docker Compose"
    exit 1
fi

# 创建数据目录
mkdir -p data/{videos,audios,transcripts,models}

# 复制环境变量
if [ ! -f .env ]; then
    cp .env.example .env
    echo "📝 已创建 .env 文件，请配置 Dify API Key 后重新启动"
    echo ""
    echo "配置步骤："
    echo "  1. 先启动 Dify（如果还没有的话）"
    echo "  2. 在 Dify 中创建一个知识库（Dataset）"
    echo "  3. 在 Dify 中创建一个对话应用并关联知识库"
    echo "  4. 将 API Key 和 Dataset ID 填入 .env 文件"
    echo ""
    echo "详细说明请查看 README.md"
    echo ""
fi

echo "🚀 启动服务..."
echo ""
echo "服务列表："
echo "  • 抖音爬虫 API  : http://localhost:5000"
echo "  • 编排服务 API  : http://localhost:8000"
echo "  • 编排服务文档  : http://localhost:8000/docs"
echo "  • Dify (单独部署): http://localhost:8080"
echo ""

$COMPOSE_CMD up -d

echo ""
echo "✅ 服务启动中，请等待 1-2 分钟..."
echo ""
echo "查看状态: $COMPOSE_CMD ps"
echo "查看日志: $COMPOSE_CMD logs -f"
echo "停止服务: $COMPOSE_CMD down"
