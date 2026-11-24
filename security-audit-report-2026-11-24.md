# 安全审计报告（第二轮）

> 生成时间：2026-11-24 14:06
> 审计工具：Codex Security Audit Skill
> 项目：RocketMQ Console（阿里云 RocketMQ 5.0 团队管理面板）

## 审计概要

- **审计范围**：`app/`、`scripts/`、`tests/`、`deploy/`、`Dockerfile`、`docker-compose.yml`、`requirements.txt`、`.env.example`、`.gitignore`、`README.md`；`.env` 仅检查凭据暴露，值未写入报告。
- **扫描文件数**：55 个源码/静态/部署文件，另加根配置文件。
- **重点新增功能**：消息轨迹、在线消费者/线程栈、Topic 订阅反查、接入点/认证/配额、消费位点重置。
- **依赖漏洞**：`pip-audit -r requirements.txt` 未发现已知 CVE。
- **回归测试**：**41 passed**。
- **结论**：未发现可由未授权远程用户直接利用的代码漏洞（无 SQL 注入、命令执行、模板 XSS、SSRF、路径遍历、CSRF 缺失）。仍有 **1 项高危运维风险（`.env` 静态 AK）** 未解决，以及若干已接受/运维风险。

## 本次新增功能的访问控制

| 功能/路由 | 权限 | 保护措施 |
|---|---|---|
| `GET /messages/{id}/trace` | viewer（`message:trace`） | 只读；审计查询条件，不记录消息体 |
| `GET /groups/{id}/consumers/{client}/stack` | operator/admin（`consumer:stack`） | 只读；审计查看行为 |
| `GET/POST /groups/{id}/reset-offset` | admin（`group:reset_offset`） | CSRF、输入 Group ID 确认、参数校验、成功/失败审计 |
| `GET /topics/{name}` 订阅反查 | viewer | 只读；输出自动转义 |
| `GET /` 接入点/认证/配额 | viewer | 只读；已移除实例用户名/密码回显 |

## 发现与处理

### [VULN-001] `.env` 中的长期静态 AccessKey 仍未解决

- **严重级别**：高危（运维/凭据风险）
- **漏洞类型**：凭据保护不当
- **文件位置**：`.env:17-18`（值已脱敏，未写入报告）
- **风险描述**：真实、长期有效的 AK/SK 明文保存在 `.env`。主机被入侵、目录被同步/备份或误打包时，攻击者可直接调用阿里云 OpenAPI，权限取决于该 RAM 用户实际绑定的策略。
- **当前状态**：**未修复**。`.env` 已被 `.gitignore` 忽略，Windows ACL 仅当前用户/管理员/SYSTEM；但仍是长期凭据。
- **修复建议**：
  1. 立即在 RAM 控制台轮换该 AK，核对权限范围；
  2. 使用专用 RAM 用户 + `deploy/ram-policy.json` 最小权限；
  3. 生产环境删除 `.env` 中 AK，ECS 绑定实例 RAM 角色，应用自动使用 STS；
  4. 不将 `.env` 纳入镜像、共享目录或备份。
- **本次加固**：启动日志新增静态 AK 告警；`.env` 未进入 Git。
- **参考**：CWE-522 / CWE-798

### [VULN-002] 实例账号用户名在概览页回显（已修复）

- **严重级别**：中危（信息暴露/凭证边界不一致）
- **漏洞类型**：敏感信息暴露
- **文件位置**：`app/aliyun_types.py`、`app/aliyun_service.py`、`app/templates/dashboard.html`
- **风险描述**：新增的“接入点/认证”卡片把 `GetInstance` 返回的实例账号用户名展示给 viewer。虽然没有密码，但这与“实例凭证不在面板回显”的安全边界不一致，也为凭证攻击提供了辅助信息。
- **修复**：
  - 删除 `InstanceInfo.account_username` 字段；
  - `_map_instance_detail` 不再读取 `account_info.username`；
  - 概览页只显示“系统初始化 · 面板不展示用户名和密码”。
- **状态**：已修复，回归测试通过。
- **参考**：CWE-200 / CWE-522

### 已修复的健壮性问题（非安全漏洞）

- **Topic 订阅一致性布尔值导致 500**：真实 API 的 `consistency` 返回布尔值，原代码按字符串调用 `.upper()`。已统一规范化为 `一致/不一致`，`status_class` 兼容布尔/字符串/None，并补回归测试。真实实例验证返回 `['一致']`。
- **静态资源 http:// 与 CSP**：静态资源已改为 `/static/...` 根相对路径，避免 HTTPS 页面加载 HTTP 资源；新增回归测试。

## 历史问题复核（均已修复）

| 编号 | 问题 | 状态 |
|---|---|---|
| VULN-101 | `next` 参数开放重定向（反斜杠绕过） | 已修复，统一 `safe_next_url` |
| VULN-102 | 直接信任 X-Forwarded-For 导致 IP 伪造/限流绕过 | 已修复，改用 `request.client.host`；Nginx 覆盖 XFF |
| VULN-103 | 登录限流可按用户名轮换绕过并灌审计 | 已修复，增加同 IP 20 次/15 分钟上限 |
| VULN-104 | 默认 SECRET_KEY 仅告警 | 已修复，非 Mock 模式强制至少 32 字符且非默认值 |
| VULN-105 | 用户名存在性时序侧信道 | 已修复，未知用户执行 dummy argon2 校验 |
| VULN-106 | 密码长度无上限 | 已修复，8–128 位 |
| VULN-107 | CSRF 缺失 | 复核：所有 POST 路由均调用 `read_form_with_csrf` |
| VULN-108 | 权限键拼写错误 | 新增测试扫描所有 `require_permission`/`can(...)`，确保键存在于 `PERMISSIONS` |

## 已接受 / 残余风险

1. **位点重置无二次认证**：仅 admin、CSRF、输入 Group ID 确认、审计；但没有 MFA/密码二次确认。建议对高风险管理操作接入 MFA 或 step-up re-auth。
2. **轨迹/线程栈含内部元数据**：轨迹含客户端主机、用户名、事务 ID；线程栈含类名/调用路径。已按角色拆分（轨迹 viewer、线程栈 operator/admin）并审计，属于已接受风险。
3. **URL/访问日志**：消息查询、轨迹、线程栈的参数（msgId、Key、clientId、时间）会出现在 Nginx/Uvicorn 访问日志。建议对 `/messages`、`/trace` 日志隐藏 `$args`，或缩短日志保留期。
4. **限流为进程内实现**：单 worker 有效，重启清零；多副本需 Redis。当前部署明确单 worker。
5. **Cookie Secure / HSTS**：`.env` 当前 `COOKIE_SECURE=false`（本地 HTTP）。HTTPS 部署必须设为 `true`；Nginx 示例已含 HSTS。启动日志会告警。
6. **演示库弱口令**：`data/dev.db` 仅本地演示，已被 Git 忽略；上线前删除，不要共享/备份。
7. **审计防篡改**：SQLite 与本地日志可被主机管理员修改；建议同步到 SLS/只追加存储并设置告警。
8. **无 MFA / 无自助改密**：建议为 admin 增加 TOTP 或 SSO，并增加用户自助修改密码。
9. **消息轨迹/巡检依赖实例能力**：轨迹需实例开启；线程栈取决于客户端版本。这是功能限制，不是安全漏洞。

## 验证记录

- `pytest`：**41 passed**。
- `pip-audit -r requirements.txt`：**No known vulnerabilities found**。
- 自动化扫描：无 `|safe`/模板注入、无 `eval`/`exec`/`subprocess`/`os.system`、无硬编码 AK/私钥；`innerHTML` 仅用于静态模板和日期数字。
- CSRF 复核：所有 POST 路由均校验 CSRF。
- 权限复核：新增测试确保所有引用的权限键均有定义，角色值合法。
- 真实实例只读验证：在线消费者 1 个、线程栈 35 帧、订阅反查可用、消息轨迹 producer=1/consumer=1、接入点 2 个、配额 6 项；**未对真实实例执行 ResetConsumeOffset**。
- 说明：本机未安装 Docker/Nginx，镜像构建与 Nginx 配置未做运行时验证；上线前需执行 `docker compose build` 与 `nginx -t`。

## 最终结论

本次新增功能未引入可被未授权远程用户直接利用的代码漏洞；高风险项仍是**长期静态 AK 的存放方式**，需要按上述建议轮换并切换 ECS RAM 角色。安全是持续过程，本报告不构成“绝对无漏洞”的保证，建议把 `pip-audit`、权限键扫描和依赖更新纳入 CI。
