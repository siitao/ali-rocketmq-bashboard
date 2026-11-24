# RocketMQ Console

阿里云 **云消息队列 RocketMQ 5.0** 的团队管理面板。用一套面板账号替代开发同学登录阿里云控制台，后端只使用一个最小权限的 RAM 角色调用 OpenAPI，所有关键操作按人记录审计日志。

> 开源 `rocketmq-dashboard` / `rocketmq-console` 走标准 Remoting + 社区 ACL，无法连接阿里云托管 5.x 实例（5.x 是 gRPC/HTTP 接入层 + 阿里云签名），所以本项目基于官方 OpenAPI `2022-08-01` 实现。

## 功能

- **只读看板**：实例状态、Topic/Group 数量、实例信息、接入点
- **Topic 管理**：列表/搜索、详情、创建、修改、删除（删除仅管理员，需输入名称确认）
- **Consumer Group 管理**：列表/搜索、详情、创建、修改、删除（同上）
- **消费堆积**：`GetConsumerGroupLag`，按 Topic 展示待消费/处理中/投递延迟
- **订阅关系**：`ListConsumerGroupSubscriptions`
- **消息查询**：按 Topic + 时间范围 / msgId / Key 检索，`GetMessageDetail` 查看消息体与属性
- **账号与权限**：本地账号，viewer / operator / admin 三角色，服务端 RBAC
- **审计日志**：登录、查询、增删改全部落库，记录用户、实例、对象、结果、IP、参数（不记录消息体）
- **安全**：argon2id 密码、签名会话、CSRF、登录限流、CSP、实例白名单

不包含（v1）：消息收发、消费位点重置、告警图表、自助注册、多地域。

## 架构

```
浏览器（内网/VPN） → Nginx(TLS) → FastAPI + Jinja2
                                      ├─ SQLite：用户 / 审计
                                      └─ alibabacloud_rocketmq20220801
                                            ↑ 凭证链：ECS RAM 角色 → 环境变量 AK
                                            ▼
                                       RocketMQ 5.0 实例（白名单）
```

管理操作只走 OpenAPI（RAM 鉴权）。实例的“智能身份识别 / ACL”用户名密码只用于消息收发客户端接入，面板**不读取、不存储、不回显**这对凭证。

## 快速开始（Mock 模式，无需云凭证）

要求 Python 3.11+。

```bash
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\activate
# Linux/macOS
.venv/bin/pip install -r requirements.txt
source .venv/bin/activate
```

后续命令默认在已激活 venv 的终端中执行。

复制配置并至少修改 `SECRET_KEY`：

```bash
copy .env.example .env        # Windows
cp .env.example .env          # Linux/macOS
```

`.env` 中设置：

```dotenv
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))" 的输出>
MOCK_ALIYUN=1
ALLOWED_INSTANCE_IDS=rmq-cn-mock-001
```

创建管理员并启动：

```bash
python -m app.cli create-admin
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>。Mock 模式自带 Topic、Group、订阅、堆积和消息样例，所有操作只改内存数据。

## 接入真实实例

### 1. 配置白名单与地域

```dotenv
MOCK_ALIYUN=0
ALIYUN_REGION=cn-hangzhou
ALLOWED_INSTANCE_IDS=rmq-cn-xxxxxxxx
SECRET_KEY=<随机 64 位 hex>
COOKIE_SECURE=true
```

`ALLOWED_INSTANCE_IDS` 是应用层硬白名单，多个实例用英文逗号分隔；未配置时服务拒绝启动。

### 2. 凭证：优先使用 ECS RAM 角色

部署在**同账号的阿里云 ECS** 上时，不需要在服务器保存 AK：

1. 新建 RAM 角色，信任实体选“阿里云 ECS”，给角色绑定自定义策略；
2. 策略模板见 [`deploy/ram-policy.json`](deploy/ram-policy.json)，把 `cn-hangzhou`、`1234567890123456`、`rmq-cn-xxxxxxxx` 替换成实际值；
3. 把角色绑定到运行面板的 ECS 实例，重启容器/进程。

`ListInstances` 通常不支持资源级限制，模板中单独放开 `*`，真正的实例范围由应用的 `ALLOWED_INSTANCE_IDS` 兜底。

本地调试才使用环境变量 AK（不要提交到仓库）：

```dotenv
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
```

凭证链由 `alibabacloud_credentials` 默认提供者处理：环境变量优先，其次 ECS 实例角色。

### 3. 只读冒烟

先跑只读检查，确认权限和网络都没问题：

```bash
python scripts/smoke_aliyun.py --instance-id rmq-cn-xxxxxxxx
```

### 4. 创建管理员

```bash
python -m app.cli create-admin
```

管理员登录后可在“用户”页创建 viewer/operator 账号。

## Docker 部署（推荐）

```bash
cp .env.example .env          # 修改 SECRET_KEY、ALLOWED_INSTANCE_IDS、ALIYUN_REGION
docker compose up -d --build
docker compose exec app python -m app.cli create-admin
docker compose logs -f app
```

默认只监听 `127.0.0.1:8000`，由宿主机 Nginx 反向代理。数据库和审计日志存放在命名卷 `rocketmq-data`：

```bash
# 备份
docker cp rocketmq-console:/data/app.db ./app-$(date +%F).db
```

如需直接通过内网 IP 访问，修改 `docker-compose.yml` 的端口映射：

```yaml
ports:
  - "10.0.0.12:8000:8000"
```

如果容器内无法获取 ECS 角色凭证（日志出现 metadata/credential 错误），把服务改为 `network_mode: host` 并去掉 `ports`（需确认宿主机 8000 端口未被占用）。

## Nginx / HTTPS

示例见 [`deploy/nginx.conf.example`](deploy/nginx.conf.example)：终止 TLS、转发真实 IP、可选内网网段 allowlist。启用 HTTPS 后把 `.env` 中的 `COOKIE_SECURE` 设为 `true`。

启动命令需要信任代理头（Dockerfile 已带；本机直接运行时）：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips="127.0.0.1" --workers 1
```

只信任本机 Nginx：Nginx 必须**覆盖** `X-Forwarded-For`（示例配置已改为 `$remote_addr`），否则客户端可伪造来源 IP，绕过登录限流并污染审计日志。

### 反向代理后静态资源变成 http://

如果浏览器控制台出现类似：

```
Connecting to 'http://your-domain/static/app.css' violates ... connect-src 'self'
```

说明应用没有识别到 Nginx 已经终止 HTTPS，生成了 `http://` 的静态资源地址，被 HTTPS 页面的 CSP/混合内容策略拦截。

处理方式：

1. Nginx 确认有 `proxy_set_header X-Forwarded-Proto $scheme;`；
2. Uvicorn 启动时带 `--proxy-headers --forwarded-allow-ips=127.0.0.1`（Dockerfile 已带）；
3. 模板中的静态资源已改为 `/static/...` 根相对路径，会跟随页面协议；
4. 重启应用并强制刷新浏览器（Ctrl+F5）；
5. 不要通过放宽 CSP 允许 `http://` 来绕过，根因是协议识别和静态资源地址。

HTTPS 部署还应设置 `COOKIE_SECURE=true`，并确保上面的代理头配置生效。

**必须单 worker**：登录限流和 OpenAPI 缓存都是进程内状态。

## 安全模型与上线迁移

- 面板账号与阿里云 RAM 完全解耦：开发同学只需要面板账号，不需要控制台权限。
- 面板后端角色只授予上述 RocketMQ 操作，且应用层再限制实例白名单。
- 密码 argon2id 哈希；会话 Cookie 签名、HttpOnly、SameSite=Lax；所有 POST 校验 CSRF；登录失败 5 次 / 15 分钟锁定（同一 IP 跨用户名最多 20 次 / 15 分钟）。
- 非 Mock 模式下 `SECRET_KEY` 必须至少 32 字符，否则服务拒绝启动；`COOKIE_SECURE=true` 会在 HTTPS 部署时给 Cookie 加 Secure 标记。
- 所有 HTML 响应设置 `Cache-Control: no-store`，避免消息内容/审计日志留在浏览器缓存。
- Nginx 示例包含 TLS 1.2/1.3、HSTS，并覆盖 `X-Forwarded-For` 防止来源伪造。
- 消息查询需要 `message:query`（viewer 默认有）；查询条件和 msgId 会审计，**消息体不写审计日志**。
- 删除 Topic/Group 仅 admin 可用，必须输入完整名称确认，操作不可恢复。
- `.env` 中的长期 AK 仅用于本地调试：请使用专用 RAM 用户、最小权限并在泄露风险出现时轮换；生产环境删除 AK，改用 ECS 实例 RAM 角色。
- `data/dev.db` 是本地演示库（含弱密码演示账号），不要复制到生产环境或共享备份。
- 上线步骤建议：
  1. 先给 2–3 名开发开 viewer/operator 账号试用；
  2. 确认面板覆盖日常操作后，移除开发 RAM 账号的控制台 / RocketMQ 权限；
  3. 用 ActionTrail 监控面板角色的 OpenAPI 调用，用面板审计日志定位到人。

## 配置项

| 变量 | 必填 | 说明 |
|---|---|---|
| `SECRET_KEY` | 是 | 会话签名密钥，随机 64 位 hex |
| `ALLOWED_INSTANCE_IDS` | 是（真实模式） | 允许管理的实例 ID，逗号分隔 |
| `ALIYUN_REGION` | 是 | 实例地域，默认 `cn-hangzhou` |
| `MOCK_ALIYUN` | 否 | `1` 使用内存 Mock，默认 `0` |
| `ALIYUN_ENDPOINT` | 否 | 覆盖默认 `rocketmq.{region}.aliyuncs.com` |
| `DATABASE_URL` | 否 | 默认 `sqlite:///./data/app.db`，容器内为 `/data/app.db` |
| `COOKIE_SECURE` | 否 | HTTPS 部署时设为 `true` |
| `SESSION_TTL_HOURS` | 否 | 会话有效期，默认 8 |
| `DEFAULT_MESSAGE_QUERY_MINUTES` | 否 | 消息查询默认时间窗，默认 30 |
| `MAX_MESSAGE_QUERY_HOURS` | 否 | 单次查询最大跨度，默认 24 |
| `LOG_LEVEL` | 否 | 默认 `INFO` |

完整示例见 [`.env.example`](.env.example)。

## 测试

```bash
.venv\Scripts\python.exe -m pytest
# 或
.venv/bin/python -m pytest
```

覆盖：登录/限流、CSRF、三角色越权、实例白名单、审计落库、Mock CRUD、消息查询与详情、全部页面渲染。

升级 Aliyun SDK 后可运行维护脚本核对方法与字段：

```bash
python scripts/inspect_sdk.py
python scripts/inspect_details.py
```

## 目录结构

```
app/
  main.py            FastAPI 装配、异常处理、安全响应头
  config.py          环境变量配置
  db.py / models.py  SQLite、User、AuditLog
  auth.py            当前用户/权限依赖
  security.py        argon2、CSRF、登录限流
  rbac.py            角色与权限矩阵
  aliyun_service.py  RocketMQ OpenAPI 封装（缓存/白名单/错误映射）
  mock_service.py    内存 Mock
  routers/           auth / dashboard / topics / groups / messages / admin
  templates/         Jinja2 页面
  static/            CSS / JS
tests/               pytest 测试套件
scripts/             SDK 核对、只读冒烟
deploy/              Nginx 示例、RAM 策略模板
```

## 限制与注意事项

- 单实例部署（SQLite + 进程内限流/缓存），不要开多 worker 或多副本。
- 仅支持一个地域；多地域需要扩展 `list_instances` 与实例-地域映射。
- 消息查询时间按**北京时间（UTC+8）**解释，API 要求 `YYYY-MM-DD HH:MM:SS`。
- Topic/Group 删除不可恢复，也不会连带清理已写入的消息。
- 面板不提供消息发送和位点重置；如需要，可在后续版本基于 `ResetConsumeOffset` 扩展并保持 admin-only。
- 审计日志默认长期保留，建议定期备份 `/data/app.db`；如合规要求长期归档，可增加导出任务。
