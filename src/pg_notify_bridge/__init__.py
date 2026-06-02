"""PostgreSQL NOTIFY 到 Webhook 的桥接服务包。

持续 LISTEN 指定 PostgreSQL 频道，并将收到的 NOTIFY 消息
异步转发到配置的 HTTP Webhook 端点。
"""

__version__ = "1.0.0"
