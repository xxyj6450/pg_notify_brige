# 使用与运维手册

## 环境变量参考

### 必填

| 变量 | 示例 | 说明 |
|------|------|------|
| `PG_DSN` | `postgresql://user:pass@db:5432/app` | PostgreSQL 连接 URL |
| `PG_CHANNELS` | `orders,inventory` | 逗号分隔，至少一个频道 |
| `WEBHOOK_URL` | `https://hooks.example.com/notify` | POST 目标地址 |

### 可选

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WEBHOOK_TIMEOUT` | `30` | 单次 HTTP 请求超时（秒） |
| `WEBHOOK_MAX_RETRIES` | `3` | 失败后额外重试次数 |
| `WEBHOOK_RETRY_BACKOFF` | `1.0` | 重试间隔基数（秒），第 n 次等待 n×backoff |
| `WEBHOOK_HEADERS` | `{"Content-Type":"application/json"}` | JSON 对象字符串，自定义请求头 |
| `LISTEN_TIMEOUT` | `10` | pgnotify select 超时（秒），用于心跳检测 |
| `RECONNECT_DELAY` | `5` | 数据库断连后重连等待（秒） |
| `WORKER_THREADS` | `4` | Webhook 并发 worker 数 |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## 本地开发

### Linux / macOS

```bash
cp .env.example .env
# 编辑 .env

make install
make run
```

等价命令：

```bash
.venv/bin/python -m pg_notify_bridge
```

### Windows

Windows 无法运行 pgnotify 监听循环，请使用 Docker 或在 WSL2 中开发：

```powershell
docker build -t pg-notify-bridge .
docker run --rm --env-file .env pg-notify-bridge
```

虚拟环境安装（仅用于编辑/打包）：

```powershell
.\scripts\setup.ps1
```

## Docker 部署

### 单容器

```bash
docker build -t pg-notify-bridge:latest .
docker run -d \
  --name pg-notify-orders \
  --restart unless-stopped \
  --env-file .env \
  pg-notify-bridge:latest
```

### 多容器（docker compose）

1. 为每个业务域复制 env 文件：

```bash
cp .env.example .env.orders
cp .env.example .env.inventory
```

2. 分别设置 `PG_CHANNELS` 与 `WEBHOOK_URL`

3. 启动：

```bash
docker compose up -d
docker compose logs -f bridge-orders
```

### 生产建议

- 使用 `--restart unless-stopped` 或 K8s Deployment
- 将敏感信息放在 secrets / 密钥管理服务，不要提交到 Git
- 限制容器日志大小（compose 中已示例 `json-file` 轮转）
- Webhook 端实现幂等（按 `channel` + `payload` + 业务键去重）

## PostgreSQL 侧配置

### 发送测试通知

```sql
NOTIFY orders, '{"event":"created","id":1}';
```

### 触发器示例

```sql
CREATE OR REPLACE FUNCTION notify_orders()
RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('orders', row_to_json(NEW)::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_orders_notify
AFTER INSERT ON orders
FOR EACH ROW EXECUTE FUNCTION notify_orders();
```

### 权限

监听用户需要对目标库有 `CONNECT` 权限；`LISTEN` 不需要表级权限，但需能建立会话。

## 日志说明

典型启动日志：

```
2026-05-30 10:00:00 | INFO     | __main__ | pg-notify-bridge starting
2026-05-30 10:00:00 | INFO     | __main__ | Configuration: {...}
2026-05-30 10:00:00 | INFO     | listener | Starting listener | channels=orders, inventory
2026-05-30 10:00:00 | INFO     | listener | Connected to PostgreSQL, subscribing to channels
```

收到消息：

```
2026-05-30 10:00:05 | INFO     | listener | NOTIFY received | channel=orders | pid=1234 | payload={...}
2026-05-30 10:00:05 | INFO     | forwarder | Webhook delivered | channel=orders | pid=1234 | status=200 | attempt=1
```

排查问题时可将 `LOG_LEVEL=DEBUG` 打开 idle timeout 与连接细节。

## 常见问题

### 1. Configuration error: Missing required environment variable

检查容器或 shell 是否注入了 `PG_DSN`、`PG_CHANNELS`、`WEBHOOK_URL`。

### 2. PostgreSQL connection error / 不断 Reconnecting

- 确认 DSN、网络、防火墙、PgBouncer 模式（LISTEN 需直连 PostgreSQL，一般不能经 transaction pooling）
- 检查 `max_connections` 与连接数

### 3. Webhook delivery exhausted retries

- 检查 `WEBHOOK_URL` 可达性与 TLS 证书
- 增大 `WEBHOOK_TIMEOUT` 或 `WEBHOOK_MAX_RETRIES`
- 下游返回 4xx 时需修复请求格式或鉴权头

### 4. 多实例收到重复消息

同一频道被多个 bridge 实例监听时，每个实例都会收到 NOTIFY。按业务域拆分频道，或只部署单实例。

## 维护操作

| 操作 | 命令 |
|------|------|
| 查看日志 | `docker compose logs -f <service>` |
| 滚动重启 | `docker compose up -d --force-recreate <service>` |
| 更新镜像 | `docker compose build && docker compose up -d` |
| 优雅停止 | `docker stop <container>`（发送 SIGTERM，等待在途 Webhook） |

## 升级依赖

```bash
pip install --upgrade pgnotify httpx psycopg2-binary
pip freeze > requirements.txt
docker build -t pg-notify-bridge:latest .
```

建议在测试环境验证后再滚动更新生产容器。
