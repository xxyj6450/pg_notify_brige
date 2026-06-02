# 架构设计

## 概述

pg-notify-bridge 是一个单进程、长期运行的桥接服务：一端通过 PostgreSQL `LISTEN` 订阅通知，另一端将消息异步投递到 HTTP Webhook。

```
┌─────────────────┐     NOTIFY      ┌──────────────────┐     HTTP POST     ┌─────────────┐
│  PostgreSQL     │ ──────────────► │ pg-notify-bridge │ ────────────────► │   Webhook   │
│  (pg_notify)    │   LISTEN 长连接  │  (本服务)         │   异步线程池       │  (下游系统)  │
└─────────────────┘                 └──────────────────┘                   └─────────────┘
```

## 核心组件

### 1. 配置层 (`config.py`)

- 启动时从环境变量加载配置
- 校验必填项与数值范围
- 日志中输出脱敏后的 DSN（隐藏密码）

### 2. 监听层 (`listener.py`)

- 使用 [pgnotify](https://github.com/djrobstep/pgnotify) 的 `await_pg_notifications` 与 `get_dbapi_connection`
- 对配置的多个频道执行 `LISTEN`
- `LISTEN_TIMEOUT` 周期内无消息时做 `SELECT 1` 健康检查
- 连接异常时按 `RECONNECT_DELAY` 自动重连
- 捕获 `SIGINT` / `SIGTERM` 优雅退出

### 3. 转发层 (`forwarder.py`)

- 收到 NOTIFY 后立即 `submit` 到 `ThreadPoolExecutor`，**不阻塞**监听循环
- 使用 `httpx` 同步客户端在 worker 线程中 POST JSON
- 支持超时、HTTP 错误、网络错误的指数退避重试（`WEBHOOK_MAX_RETRIES` × `WEBHOOK_RETRY_BACKOFF`）
- 进程退出前 `wait_for_pending` 尽量完成在途请求

### 4. 日志层 (`logging_config.py`)

- 统一格式：`时间 | 级别 | 模块 | 消息`
- 降低 httpx/httpcore 噪声日志级别

## 数据流

1. 应用或触发器执行 `NOTIFY channel, 'payload'`
2. pgnotify 在 `select()` 循环中收到通知并 yield
3. listener 记录 INFO 日志，调用 `forwarder.submit()`
4. worker 线程构造 JSON 并 POST 到 `WEBHOOK_URL`
5. 成功或重试耗尽后记录相应日志

## 多实例模型

每个容器/进程是 **独立监听器**：

| 实例 | PG_CHANNELS | WEBHOOK_URL | 用途 |
|------|-------------|-------------|------|
| bridge-orders | orders | https://api/a/webhook | 订单域 |
| bridge-inventory | inventory,stock | https://api/b/webhook | 库存域 |

同一频道被多个实例 `LISTEN` 时，PostgreSQL 会向 **每个** 连接广播通知（符合 NOTIFY 语义）。若只需一份投递，应只部署一个对应实例，或在 Webhook 侧做幂等。

## 故障与恢复

| 场景 | 行为 |
|------|------|
| PostgreSQL 断连 | 记录 ERROR，等待 `RECONNECT_DELAY` 后重连 |
| 监听空闲 | 周期性健康检查，失败则触发重连 |
| Webhook 超时/5xx | 按配置重试，失败后 ERROR 日志（消息不会持久化队列） |
| SIGTERM (Docker stop) | 停止监听，等待在途 Webhook 完成后退出 |

## 已知限制

1. **无持久化队列**：Webhook 长期不可用时，重试耗尽后消息丢失（与 NOTIFY 本身 ephemeral 特性一致）
2. **Unix 依赖**：pgnotify 使用 `fcntl`/`select`，需在 Linux/macOS 或 Docker 中运行
3. **payload 大小**：受 PostgreSQL `NOTIFY` 约 8000 字节限制

## 扩展建议

- 需要可靠投递：在 Webhook 前增加消息队列（Redis/RabbitMQ），或改用 logical replication
- 需要认证：通过 `WEBHOOK_HEADERS` 注入 Bearer Token 等
- 需要监控：采集日志或对接 Prometheus（可后续增加 metrics 端点）
