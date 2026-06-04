# pg-notify-bridge

将 PostgreSQL `NOTIFY` 消息实时转发到 HTTP Webhook 的轻量服务。基于 [pgnotify](https://github.com/djrobstep/pgnotify) 实现多频道长期监听，Webhook 投递在后台线程池中异步执行，适合 Docker 中长期运行。

本项目由[cursor](https://www.cursor.com/)免费Auto模式一次性开发完成。

## 功能

- 使用 **pgnotify** 持续 `LISTEN` 一个或多个 PostgreSQL 频道
- 收到通知后 **异步 POST** 到指定 Webhook（不阻塞监听循环），例如JIRA、企业微信、Zabbix等
- 全部配置通过 **环境变量** 注入，便于多实例部署
- 内置连接断线重连、Webhook 超时/重试、优雅退出（SIGINT/SIGTERM）
- 结构化控制台日志，便于运维排查

## 快速开始

### 1. 配置环境变量

复制示例文件并修改：

```bash
cp .env.example .env
```

必填项：

| 变量 | 说明 |
|------|------|
| `PG_DSN` | PostgreSQL 连接串，如 `postgresql://user:pass@host:5432/db` |
| `PG_CHANNELS` | 逗号分隔的频道名，如 `orders,inventory` |
| `WEBHOOK_URL` | 接收通知的 HTTP 端点 |

完整变量说明见 [.env.example](.env.example) 与 [docs/OPERATIONS.md](docs/OPERATIONS.md)。

### 2. 本地虚拟环境（开发）

**Linux / macOS：**

```bash
make install
make run
```

**Windows PowerShell：**

```powershell
.\scripts\setup.ps1
Copy-Item .env.example .env
# 编辑 .env 后运行
.\.venv\Scripts\python.exe -m pg_notify_bridge
```

> **注意**：pgnotify 依赖 `fcntl` 等 Unix API，**Windows 上无法直接运行监听逻辑**。本地开发请在 Linux/macOS 或 Docker 中运行。

### 3. Docker 部署

```bash
docker build -t pg-notify-bridge .
docker run --rm --env-file .env pg-notify-bridge
```
### 4. Docker Hub 镜像

```bash
docker pull hesonglai/pg_notify_bridge:latest

```
### 5. 示例脚本
maxkb的对话、工具调用监控示例
- [maxkb/monitor_chat.sql](examples/maxkb/monitor_chat.sql)
  - 监听 `chat` 频道
 - [monitor_tool_record.sql](examples/maxkb/monitor_tool_record.sql)
  - 监听 `tool_record` 频道

### 6. 多实例部署

每个容器实例使用 **独立的环境变量文件**，监听不同频道、转发到不同 Webhook。示例见 [docker-compose.yml](docker-compose.yml)：

```bash
cp .env.example .env.orders
cp .env.example .env.inventory
# 分别修改 PG_CHANNELS、WEBHOOK_URL 等

docker compose up -d
```

## Webhook 请求体

每条 NOTIFY 会 POST 如下 JSON：

```json
{
  "channel": "orders",
  "payload": "{\"id\": 1}",   # 注意：这里是文本字符串，json/xml等格式需要自行解析
  "pid": 12345,
  "received_at": "2026-05-30T08:00:00.123456+00:00"
}
```

## 项目结构

```
pg_notify/
├── src/pg_notify_bridge/   # 主程序
│   ├── config.py           # 环境变量配置
│   ├── listener.py         # pgnotify 监听与重连
│   ├── forwarder.py        # 异步 Webhook 转发
│   └── logging_config.py   # 日志格式
├── docs/
│   ├── ARCHITECTURE.md     # 架构说明
│   └── OPERATIONS.md       # 运维手册
├── examples/               # 示例脚本
│   ├── maxkb/monitor_chat.sql
│   ├── maxkb/monitor_chat_update.sql
│   ├── maxkb/monitor_tool_record.sql
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
├── Makefile
└── scripts/setup.ps1
```

## 文档

- [架构设计](docs/ARCHITECTURE.md)
- [使用与运维](docs/OPERATIONS.md)

## 依赖

- Python 3.10+
- [pgnotify](https://github.com/djrobstep/pgnotify)
- psycopg2-binary
- httpx

## cursor 提示词 

这是一个python的postgresql通知处理项目，要求如下：
1. 要使用github的pgnotify（https://github.com/djrobstep/pgnotify ）来实现， 用于永久实时监听pg_notify特定渠道（支持多个）的消息，并将接收到的消息异步转发到指定的webhook
2. postgresql和webhook的相关信息从环境变量中读取。
3. 项目将部署到docker中运行，要将依赖文件和dockerfile都准备好，未来可以启动多个容器实例处理不同的消息
4. 而且为方便管理还要处理好Python虚拟环境。
5. 为确保长期稳定运行，要处理好各类异常和超时等，并在控制台输出好日志
6. 同时项目文档也是很重要的，项目描述、项目架构、项目使用和维护资料等都要准备好。
7. 每个类、函数及关键代码、复杂代码、变量增加代码备注说明
如果还有需要我确定的信息你可以问我


## License

MIT
