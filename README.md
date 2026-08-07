# 抖音博主学习 Agent v2.0

> 基于高 star 开源项目构建，爬取抖音博主视频 → AI语音转文字 → 导入知识库 → 智能问答学习

## ✨ 核心亮点

**全部基于 GitHub 顶级开源项目，开发量减少 80%！**

| 组件 | 选用项目 | GitHub Stars | 我们做的 |
|------|---------|-------------|---------|
| **知识库 & 问答UI** | [Dify](https://github.com/langgenius/dify) | ⭐ 130,000+ | 0 代码 |
| **抖音爬虫** | [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | ⭐ 15,500+ | 0 代码 |
| **语音识别** | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | ⭐ 23,000+ | 薄封装 |
| **编排层** | 我们自己写 | - | ~500行 |

## 🏗️ 架构图

```
┌───────────────────────────────────────────────────────────┐
│                     用户界面 (Dify)                        │
│   知识库管理 | 对话问答 | 工作流 | 数据标注 | 可观测性     │
│                  (130k+ stars, 开箱即用)                   │
└───────────────────────────────┬───────────────────────────┘
                                │ Dify API
┌───────────────────────────────▼───────────────────────────┐
│                    编排服务 (我们写的)                     │
│              调度协调 + 数据流转 + 进度管理                │
└───────┬───────────────────────────┬───────────────────────┘
        │                           │
┌───────▼──────────┐   ┌────────────▼─────────────┐
│  抖音爬虫 API    │   │   faster-whisper 语音识别  │
│ (15.5k+ stars)   │   │      (23k+ stars)        │
│  视频解析/下载    │   │    视频 → 文字转录        │
└──────────────────┘   └──────────────────────────┘
```

## 🎯 为什么选择这些项目？

### Dify vs 自己写前端+知识库
- **省掉的工作量**：前端界面、知识库管理、文档解析、向量数据库、对话系统、Prompt 调试、用户管理、LLM 接入...
- Dify 有完整的 Web UI、API、工作流编排、可观测性
- 支持上百种 LLM（GPT、Claude、通义、智谱、Llama 等）
- 企业级成熟度，社区活跃

### Douyin_TikTok_Download_API vs 自己写爬虫
- **省掉的工作量**：抖音接口逆向、签名算法、Cookie 管理、反爬策略、Web UI...
- 15.5k stars，持续更新，支持抖音+TikTok+B站
- 提供 REST API，直接调用即可

### faster-whisper vs 原版 Whisper
- 速度提升 4 倍以上，内存占用降低
- 支持量化（INT8），CPU 也能跑
- 中文识别效果好

## 🚀 快速开始

### 前置要求

- Docker & Docker Compose
- 至少 4GB 内存（跑 Whisper base 模型）
- 可选：GPU（大幅加速语音识别）

### 第 1 步：部署 Dify（知识库 + 问答UI）

Dify 是独立的服务，需要单独部署。推荐使用官方 Docker Compose：

```bash
# 克隆 Dify
git clone https://github.com/langgenius/dify.git
cd dify/docker

# 启动（首次启动需要下载镜像，约 5-10 分钟）
docker compose up -d
```

访问 http://localhost:8080 ，注册管理员账号。

### 第 2 步：在 Dify 中创建知识库

1. 进入「知识库」页面，点击「创建知识库」
2. 命名为 "抖音博主知识库"
3. 创建后，复制知识库 ID（在 URL 或设置中可以找到）
4. 在「API 密钥」页面创建一个 API Key，复制备用

### 第 3 步：创建对话应用

1. 进入「工作室」→「创建空白应用」
2. 选择「对话型」应用
3. 在「编排」→「知识库」中关联刚才创建的知识库
4. 发布应用

### 第 4 步：配置并启动

```bash
# 进入项目目录
cd douyin-learning-agent

# 复制环境变量
cp .env.example .env

# 编辑 .env，填入 Dify 的 API Key 和知识库 ID
vim .env

# 一键启动
./start.sh
```

### 第 5 步：添加博主

```bash
# 调用编排 API 添加博主
curl -X POST http://localhost:8000/api/bloggers \
  -H "Content-Type: application/json" \
  -d '{"share_url": "https://v.douyin.com/xxxxx/"}'
```

或者直接在 Dify 里查看知识库，等视频处理完后就可以在 Dify 的对话界面问答了！

## 📁 项目结构

```
douyin-learning-agent/
├── docker-compose.yml          # Docker Compose 配置
├── start.sh                    # 一键启动脚本
├── .env.example                # 环境变量示例
├── README.md                   # 本文档
│
└── orchestrator/               # 编排服务（我们写的胶水层）
    ├── Dockerfile
    ├── requirements.txt
    ├── main.py                 # 主入口
    ├── .env.example
    └── app/
        ├── api/
        │   ├── bloggers.py     # 博主管理 API
        │   └── system.py       # 系统状态 API
        ├── services/
        │   ├── douyin_client.py    # 抖音爬虫 API 客户端
        │   ├── dify_client.py      # Dify API 客户端
        │   ├── asr_service.py      # 语音识别服务
        │   └── orchestrator.py     # 核心编排逻辑
        ├── core/
        │   ├── config.py       # 配置管理
        │   ├── database.py     # 数据库
        │   └── logger.py       # 日志
        └── models/
            └── models.py       # 数据模型
```

## 🔧 API 接口

### 博主管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/bloggers` | 添加博主（自动开始处理） |
| GET | `/api/bloggers` | 获取博主列表 |
| GET | `/api/bloggers/{id}` | 获取博主详情 |
| GET | `/api/bloggers/{id}/status` | 获取处理进度 |
| POST | `/api/bloggers/{id}/refresh` | 重新处理 |
| DELETE | `/api/bloggers/{id}` | 删除博主 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/health` | 健康检查 |
| GET | `/api/system/status` | 各服务连接状态 |
| GET | `/api/system/config` | 当前配置 |

## ⚙️ 配置说明

### 主要环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DIFY_API_BASE_URL` | Dify API 地址 | http://localhost:8080 |
| `DIFY_API_KEY` | Dify API Key（必填） | - |
| `DIFY_DATASET_ID` | Dify 知识库 ID（必填） | - |
| `DOUYIN_API_BASE_URL` | 抖音爬虫 API 地址 | http://localhost:5000 |
| `ASR_ENGINE` | 语音识别引擎 | faster-whisper |
| `WHISPER_MODEL_SIZE` | Whisper 模型大小 | base |
| `WHISPER_DEVICE` | 运行设备 (cpu/cuda) | cpu |
| `WHISPER_COMPUTE_TYPE` | 计算精度 (int8/float16) | int8 |
| `MAX_VIDEOS_PER_BLOGGER` | 每博主最大视频数（0不限） | 0 |

### Whisper 模型选择

| 模型 | 参数量 | 中文效果 | 内存占用 | 速度（CPU） |
|------|--------|---------|---------|------------|
| tiny | 39M | 一般 | ~1GB | 很快 |
| base | 74M | 可用 | ~1GB | 快 |
| small | 244M | 较好 | ~2GB | 中等 |
| medium | 769M | 好 | ~5GB | 慢 |
| large-v3 | 1550M | 最好 | ~10GB | 很慢 |

> 建议：CPU 用 `base` 或 `small`，有 GPU 用 `medium` 或 `large-v3`

## 🎯 使用流程

### 完整工作流

```
1. 添加博主链接
   ↓
2. 爬取视频列表（抖音爬虫 API）
   ↓
3. 逐个下载视频
   ↓
4. 提取音频（moviepy/ffmpeg）
   ↓
5. 语音转文字（faster-whisper）
   ↓
6. 导入 Dify 知识库（自动分块+向量化）
   ↓
7. 在 Dify 对话界面问答学习
```

### 问答学习

所有问答都在 Dify 中进行：

- 💬 **对话问答**：像聊天一样提问，基于博主视频内容回答
- 🔗 **引用溯源**：每个答案都标注引用自哪个视频
- 📊 **对话历史**：自动保存所有对话记录
- 🎨 **可定制**：可自定义 Prompt、人设、回复风格
- 📱 **多端访问**：Dify 支持 Web、微信、API 等多种接入方式

## 🔄 与 v1 版本对比

| 维度 | v1（全自研） | v2（开源优先） |
|------|-------------|---------------|
| 代码量 | ~3000 行 | ~500 行 |
| 前端 | 自己写 React | Dify 自带（更专业） |
| 知识库 | 自己封装 ChromaDB | Dify 内置（更成熟） |
| 问答系统 | 提取式（简单） | Dify + LLM（更智能） |
| 爬虫 | 自己写 | 用成熟项目 |
| 维护成本 | 高 | 低 |
| 功能丰富度 | 基础 | 丰富（工作流、Agent 等） |
| LLM 接入 | 无 | 100+ 模型 |

## 📝 注意事项

1. **合规使用**：请遵守抖音平台服务条款，仅用于个人学习
2. **Dify 部署**：Dify 组件较多（10+ 容器），确保机器有足够内存（建议 4GB 以上）
3. **模型下载**：首次运行 faster-whisper 会自动下载模型，需要联网
4. **存储空间**：视频文件会占用较大空间，注意磁盘容量
5. **处理速度**：视频转文字是最耗时的步骤，CPU 处理 1 分钟视频约需 1-2 分钟
6. **GPU 加速**：如有 NVIDIA GPU，建议设置 `WHISPER_DEVICE=cuda` 大幅提速

## 🔮 可扩展方向

得益于 Dify 的强大生态，你可以很方便地扩展：

- 🤖 **Agent 能力**：在 Dify 中配置工具调用（搜索、代码执行等）
- 🔄 **工作流**：用 Dify 工作流编排复杂的学习流程
- 📊 **数据分析**：对接 Dify 的数据分析功能
- 🌐 **多平台发布**：Dify 支持一键发布到微信、飞书、钉钉等
- 👥 **多用户**：Dify 内置用户和权限管理
- 📈 **可观测性**：Dify 有完整的日志、监控、A/B 测试

## 📄 开源协议

本项目仅为编排脚本，遵循 MIT License。
各上游项目遵循各自的开源协议：
- Dify: Apache 2.0
- Douyin_TikTok_Download_API: MIT
- faster-whisper: MIT
- Whisper: MIT

---

**少造轮子，多站在巨人的肩膀上！** 🚀
