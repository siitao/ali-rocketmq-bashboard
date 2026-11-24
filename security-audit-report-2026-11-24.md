# 安全审计报告

> 生成时间：2026-11-24 10:09
> 审计工具：Codex Security Audit Skill
> 项目：RocketMQ Console（阿里云 RocketMQ 5.0 团队管理面板）

## 审计概要

- **审计范围**：`app/`、`scripts/`、`tests/`、`deploy/`、`Dockerfile`、`docker-compose.yml`、`requirements.txt`、`.env.example`、`.gitignore`、`README.md`；`.env` 仅检查凭据暴露，值未写入报告。
- **扫描文件数**：58 个（51 个源码/静态/部署文件 + 7 个根配置文件）。
- **发现问题数**：10 个（严重 0 / 高危 1 / 中危 4 / 低危 5）。
- **依赖漏洞**：`pip-audit -r requirements.txt` 未发现已知 CVE。
- **回归测试**：29 passed。
- **总体结论**：未发现 SQL 注入、命令执行、模板 XSS、SSRF、路径遍历等可直接远程利用的漏洞。主要风险集中在**长期 AK 明文存放、代理头信任、登录限流可绕过**和**认证侧信道**。代码层已修复 6 项、部分加固 1 项；另有 3 项需要运维/流程配合。

## 漏洞详情

### [VULN-001] 长期 AccessKey 明文存放在 .env

- **严重级别**：高危
- **漏洞类型**：凭据保护不当
- **文件位置**：`.env:17-18`（值已脱敏，未写入报告）
- **风险描述**：`.env` 中是真实、长期有效的阿里云 AK/SK。任何能读取该文件的人（主机被入侵、目录被同步/备份、误打包）都可以直接调用阿里云 OpenAPI，权限范围取决于该 RAM 用户实际绑定的策略，可能超出 RocketMQ 实例。面板无法撤销或轮换该 AK。
- **漏洞代码**：
  ```dotenv
  ALIBABA_CLOUD_ACCESS_KEY_ID=<redacted>
  ALIBABA_CLOUD_ACCESS_KEY_SECRET=<redacted>
  ```
- **修复建议**：
  1. 立即在 RAM 控制台**轮换**该 AK，并核对其权限范围；
  2. 使用专用 RAM 用户，只绑定 `deploy/ram-policy.json` 中列出的 RocketMQ 操作；
  3. 生产环境删除 `.env` 中 AK，ECS 绑定实例 RAM 角色，应用会自动使用 STS；
  4. 不要把 `.env` 纳入镜像、共享目录或备份；当前 Windows ACL 已限制为当前用户/管理员/SYSTEM。
- **参考**：CWE-522 / CWE-798

### [VULN-002] next 参数开放重定向（反斜杠绕过）

- **严重级别**：中危
- **漏洞类型**：开放重定向
- **文件位置**：`app/security.py:21`（修复后）；原逻辑位于 `app/routers/auth.py` 与 `app/main.py`
- **风险描述**：原校验只拦截 `//evil.com`。攻击者可构造 `next=/\evil.example`；浏览器会把反斜杠规范化为斜杠，登录成功后跳转到外部站点，用于钓鱼或窃取信任。
- **漏洞代码**：
  ```python
  if not value or not value.startswith("/") or value.startswith("//"):
      return "/"
  return value
  ```
- **修复代码**：
  ```python
  def safe_next_url(value: str | None, default: str = "/") -> str:
      if not value:
          return default
      if any(char in value for char in ("\\", "\r", "\n", "\x00")):
          return default
      if not value.startswith("/") or value.startswith("//"):
          return default
      parsed = urlsplit(value)
      if parsed.scheme or parsed.netloc:
          return default
      return value
  ```
  登录页、登录 POST、`AuthRequired` 跳转全部统一使用该函数。
- **状态**：已修复。
- **参考**：CWE-601

### [VULN-003] 直接信任 X-Forwarded-For 导致来源 IP 伪造

- **严重级别**：中危
- **漏洞类型**：不可信代理头 / 限流绕过 / 审计污染
- **文件位置**：`app/web.py:168`；`deploy/nginx.conf.example:39`；`Dockerfile:29`
- **风险描述**：应用直接取 `X-Forwarded-For` 的第一个值，而 Nginx 使用 `$proxy_add_x_forwarded_for` 追加客户端自带头。攻击者可任意伪造来源 IP，绕过按 IP 的登录限流，并让审计日志记录虚假 IP。
- **漏洞代码**：
  ```python
  forwarded = request.headers.get("x-forwarded-for")
  if forwarded:
      return forwarded.split(",")[0].strip()
  ```
- **修复代码**：
  ```python
  def client_ip(request: Request) -> str:
      # Uvicorn ProxyHeadersMiddleware 已按 --forwarded-allow-ips 解析可信代理。
      return ((request.client.host if request.client else "") or "")[:64]
  ```
  Nginx 改为**覆盖** `X-Forwarded-For $remote_addr`；Uvicorn 只信任 `127.0.0.1` 的代理头。
- **状态**：已修复。
- **参考**：CWE-290 / CWE-348

### [VULN-004] 登录限流可按用户名轮换绕过并灌入审计日志

- **严重级别**：中危
- **漏洞类型**：暴力破解防护绕过 / 资源耗尽
- **文件位置**：`app/security.py:80-110`；`app/routers/auth.py:70`
- **风险描述**：原限流只按 `IP + 用户名` 计算（5 次/15 分钟），攻击者每次换一个用户名即可无限尝试，并且每次失败都会写入一条审计记录，造成数据库/日志膨胀。
- **修复代码**：
  ```python
  def __init__(self, max_attempts=5, max_ip_attempts=20, window_seconds=900):
      self._attempts = defaultdict(deque)      # IP + 用户名
      self._ip_attempts = defaultdict(deque)   # 仅 IP

  def is_limited(self, ip, username):
      return (len(user_bucket) >= self.max_attempts
              or len(ip_bucket) >= self.max_ip_attempts)
  ```
  同一 IP 跨用户名最多 20 次失败 / 15 分钟。
- **状态**：已修复；测试覆盖 `test_rate_limit_applies_across_usernames_from_one_ip`。
- **残余风险**：分布式 IP 轮换、进程重启会重置计数；多副本部署需改用 Redis。
- **参考**：CWE-307 / CWE-770

### [VULN-005] 默认 SECRET_KEY 仅告警，仍可启动

- **严重级别**：中危
- **漏洞类型**：不安全的默认配置
- **文件位置**：`app/main.py:55`
- **风险描述**：若部署时忘记修改 `SECRET_KEY`，攻击者可利用已知默认值伪造签名会话 Cookie，把 `user_id` 改成管理员 ID，直接接管面板。
- **修复代码**：
  ```python
  if not settings.mock_aliyun:
      if settings.secret_key.startswith("dev-only") or len(settings.secret_key) < 32:
          raise RuntimeError(
              "SECRET_KEY 未配置或长度不足 32 字符：请生成随机密钥后再启动。"
          )
  ```
- **状态**：已修复；Mock 模式不触发，便于本地开发。
- **参考**：CWE-1188 / CWE-798

### [VULN-006] 用户名存在性时序侧信道

- **严重级别**：低危
- **漏洞类型**：时序信息泄露 / 用户名枚举
- **文件位置**：`app/routers/auth.py:88-91`
- **风险描述**：原逻辑 `user is None or ... or not verify_password(...)` 在用户不存在时短路，跳过 argon2 校验；响应时间明显短于“用户存在但密码错误”，可用于枚举有效用户名。
- **修复代码**：
  ```python
  password_ok = False
  if password and len(password) <= MAX_PASSWORD_LENGTH:
      password_ok = verify_password(
          password,
          user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
      )
  ```
  用户不存在时也执行一次 argon2 校验，使耗时接近。
- **状态**：已修复。
- **参考**：CWE-208 / CWE-203

### [VULN-007] 密码长度没有上限

- **严重级别**：低危
- **漏洞类型**：输入验证不足 / 资源耗尽
- **文件位置**：`app/security.py:16`；`app/routers/admin.py:88,205`；`app/cli.py`
- **风险描述**：登录、创建用户、重置密码均只校验最小长度。超长密码会增加 argon2 输入处理开销，结合无请求体限制时可造成 CPU/内存压力。
- **修复代码**：
  ```python
  MAX_PASSWORD_LENGTH = 128
  # 登录、创建用户、重置密码、CLI 均校验 8 <= len(password) <= 128
  ```
- **状态**：已修复。
- **参考**：CWE-400 / CWE-521

### [VULN-008] Cookie Secure / HSTS / 敏感页面缓存

- **严重级别**：低危
- **漏洞类型**：传输与会话保护不足
- **文件位置**：`.env:23`（`COOKIE_SECURE=false`）；`app/main.py:69-76`；`deploy/nginx.conf.example:19-22`
- **风险描述**：若通过 HTTP 提供服务，会话 Cookie 无 Secure 标记，存在被嗅探风险；未设置 HSTS 时存在 SSL 剥离风险；消息内容和审计页面可能被浏览器缓存。
- **修复/加固**：
  - 非 Mock 模式且 `COOKIE_SECURE=false` 时启动日志告警；
  - 所有 HTML 响应增加 `Cache-Control: no-store`；
  - Nginx 示例增加 `Strict-Transport-Security`；
  - HTTPS 部署时必须在 `.env` 设置 `COOKIE_SECURE=true`。
- **状态**：已加固，仍需在 HTTPS 环境完成配置。
- **参考**：CWE-614 / CWE-319 / CWE-525

### [VULN-009] 消息查询参数进入 URL 与访问日志

- **严重级别**：低危
- **漏洞类型**：日志/URL 中的敏感信息
- **文件位置**：`app/templates/messages/query.html`（GET 表单）；`app/routers/messages.py`
- **风险描述**：Topic、msgId、Key、时间范围会出现在查询字符串中，被 Nginx/Uvicorn 访问日志、浏览器历史和 Referer 记录。消息正文不会出现在日志或审计中。
- **修复建议**：改用 POST + CSRF 查询；或在 Nginx 对 `/messages` 的访问日志隐藏 `$args`；缩短日志保留周期并限制访问权限。
- **状态**：未修复（设计权衡）。
- **参考**：CWE-532

### [VULN-010] 演示数据库使用弱口令

- **严重级别**：低危
- **漏洞类型**：弱凭据
- **文件位置**：`data/dev.db`（本地演示库）；`tests/conftest.py`
- **风险描述**：演示库包含 `admin` 等弱口令账号。文件已被 `.gitignore` 忽略，仅用于本地 Mock；若被复制到生产或共享备份，可被直接登录。
- **修复建议**：上线前删除 `data/dev.db`；不要将 `data/` 纳入镜像、备份或共享目录；生产管理员通过 `python -m app.cli create-admin` 交互式创建强密码。
- **状态**：运行时清理项。
- **参考**：CWE-521

## 已确认的安全控制（非漏洞）

- **访问控制**：viewer/operator/admin 三角色服务端校验；所有写操作 POST 路由均有 `require_permission`；实例白名单在服务层每次调用前校验，未配置时拒绝启动。
- **CSRF**：全部 POST（含登录、退出）使用会话同步 Token；`secrets.compare_digest` 比较。
- **注入**：数据库全部使用 SQLAlchemy ORM，无字符串拼接 SQL；无 `eval`/`exec`/`subprocess`/`os.system`。
- **XSS**：Jinja2 自动转义，模板中无 `|safe`；消息体、备注、审计参数均转义输出；`app.js` 的 `innerHTML` 仅用于静态模板和日期数字，不拼接用户输入。
- **SSRF/路径遍历**：没有用户可控的服务端 URL 请求；静态目录固定；无用户可控文件路径。
- **密码与会话**：argon2id；登录成功后清空并重建会话、轮换 CSRF Token；Cookie 签名、HttpOnly、SameSite=Lax。
- **安全响应头**：CSP、X-Frame-Options、X-Content-Type-Options、Referrer-Policy、Permissions-Policy、`Cache-Control: no-store`。
- **容器**：非 root UID 10001；端口默认只绑定 127.0.0.1。
- **审计**：登录成功/失败、Topic/Group 增删改、消息查询、用户管理均记录；不记录消息正文和密码。
- **依赖**：版本固定；`pip-audit` 未发现已知漏洞。

## 残余风险与加固建议

1. **管理员 MFA**：当前仅密码登录，建议为 admin 增加 TOTP 或接入公司 SSO/OIDC。
2. **多副本限流**：限流是进程内内存实现，必须单 worker；扩容时改用 Redis。
3. **审计防篡改**：SQLite 和本地日志可被主机管理员修改；建议同步到 SLS/只追加存储并配置告警。
4. **Trusted Host**：未启用 `TrustedHostMiddleware`；如暴露在不可信网络，建议配置允许域名。
5. **自助改密**：目前只能由管理员重置密码，建议增加用户自助修改密码并校验旧密码。
6. **访问日志脱敏**：见 VULN-009。
7. **Nginx 防暴力**：可在 Nginx 增加 `limit_req` 作为应用限流的补充。
8. **文件权限**：Linux/容器部署建议 `chmod 700 data`、`chmod 600 data/*.db`，并限制备份权限。
9. **依赖更新**：把 `pip-audit` 加入 CI，定期升级依赖。

## 验证记录

- `pytest`：**29 passed**（含开放重定向、XFF/限流、密码长度、中文审计动作等回归用例）。
- `pip-audit -r requirements.txt`：**No known vulnerabilities found**。
- 真实 `.env` 启动检查：`/healthz` 返回 `{"status":"ok","mock":false}`，`/login` 返回 200。
- 说明：本机未安装 Docker 与 Nginx，容器镜像和 Nginx TLS/HSTS 配置未做运行时验证；上线前需在目标环境执行 `docker compose build` 与 `nginx -t`。
