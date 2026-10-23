# 项目目标

用 Ansible 管理按需创建、销毁的 Vultr Debian 13 双栈服务器，在同一域名上提供
Hysteria2 和 SearXNG。重建时域名、认证密码、SNI 和端口保持稳定，mihomo 无需改配置。

## 代码结构

- `server`：Python 标准库入口，处理 `up` / `down`、本 checkout 文件锁和 Vault 密码选项。
- `lifecycle.yml`：本机云资源编排、调用部署、执行 HTTPS 检查。
- `tasks/cloud-discover.yml`：查找资源，核对实例及 DNS 的所有权。
- `tasks/cloud-up.yml`：创建或复用实例，启用双栈，配置网络，维护 A/AAAA，生成动态主机组。
- `tasks/cloud-wait-instance.yml`：实例及双栈状态轮询，容忍临时 API 错误并输出脱敏的最终错误。
- `scripts/check-dns`：分别诊断本机 A/AAAA，输出实际与预期地址；解析差异不阻止按 IP 部署。
- `tasks/cloud-ipv6-network.yml`：Debian IPv6 地址、RA、持久配置及路由检查。
- `tasks/cloud-down.yml`：删除本流程拥有的 DNS，再销毁实例并核验删除结果。
- `site.yml`：部署入口；按 `common` → `searxng` → `hysteria` 的顺序运行角色。
- `roles/common`：基础软件、时区和 nftables。
- `roles/searxng`：Docker Compose，服务只发布到 `127.0.0.1:8080`。
- `roles/hysteria`：二进制、服务配置、systemd 和 Cloudflare DNS-01。
- `tests`：运行实际 Ansible 任务与模板，使用离线适配器模拟云 API、服务管理和连接。

## 配置与凭据

| 文件 / 变量 | 职责 |
| --- | --- |
| `group_vars/vultr/main.yml` | 域名、邮箱、时区、服务与端口配置 |
| `group_vars/vultr/vault.yml` | 加密的 Hysteria 密码与 SearXNG 密钥；本机文件，禁止覆盖 |
| `cloud.yml` | 区域、套餐、OS ID、SSH Key UUID、私钥路径、Zone ID 与所有权标记 |
| `.envrc.local` | `VULTR_API_KEY`、`CLOUDFLARE_API_TOKEN`、可选的 `ANSIBLE_VAULT_PASSWORD` |
| `inventory/hosts.yml` | 手动管理已有服务器时使用；生命周期通过动态 inventory 部署 |
| `roles/hysteria/defaults/main.yml` | ACME 类型、令牌来源和失败重试间隔 |

`cloud.yml`、Vault、inventory 和 `.envrc.local` 均被 Git 忽略。修改示例文件时使用空值
或明确的占位值，禁止加入可直接使用的默认密码。不要读取或输出真实凭据来做普通代码审查。
含密钥的模板任务必须保留 `no_log: true`、`diff: false`，服务端配置权限为 `0600`。
本机凭据文件也应为 `0600`。不要在日志、测试快照或命令参数里放入真实密钥。

## 必须保留的行为

- 实例只按固定 label 和 ownership tag 的组合识别；名称冲突、重复资源或查询不完整时停止。
- DNS 只自动删除 comment 与本流程所有权标记匹配的记录。接管已有 A/AAAA 必须显式配置。
- 不自动重试创建实例的 POST；响应丢失后先核对远端，避免重复创建和计费。
- `up` 失败后保留实例以便修复重跑。`down` 销毁磁盘，但保留本机 Vault 与配置。
- 文件锁只防止同一 checkout 并发；不要在进程可能持锁时删除 `.lifecycle.lock`。
- 新实例同时启用 IPv4、IPv6；DNS 使用灰云 A/AAAA。升级 IPv4-only 实例需通过 Vultr 重启。
- `common` 提前刷新防火墙 handler 时，不得重启尚未安装的 Hysteria 或 Docker。
- 不使用 `flush ruleset`：Docker 和 Hysteria 会维护自己的防火墙规则。
- 镜像自带 UFW 时，先应用项目 nftables 规则再停用 UFW；配置文件未变化时也必须处理，并在需要时恢复 Docker 规则。
- 控制端委派任务显式使用本地连接，引用远端 IP 时使用原主机的 `hostvars`。
- 不把本机 DNS 缓存、代理 Fake-IP 或本地 AAAA 重写当作云端 DNS 更新失败；输出诊断并继续按 IP 部署。
- IPv6 HTTPS 自检不等于公网 IPv6 连通；HTTPS 成功也不证明 Hysteria UDP/端口跳跃可用。
- 服务端 HTTPS 就绪与控制端公网直连分别检查；公网失败应输出 curl 错误并保持失败，不得静默跳过或关闭证书校验。
- DNS-01 需要 Zone Read 和 DNS Edit；令牌还需允许服务器访问 Cloudflare API。
- ACME 429 应先修复验证原因、遵守 retry-after；不要删账户缓存或换账户绕过限额。
- 当前不跨实例保存 ACME 数据；频繁重建仍可能触及相同域名的签发限额。

## 开发与验证

从仓库根目录运行，优先进入 `nix develop`。保留 `flake.lock`；无需额外 Ansible collections。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
ansible-lint site.yml lifecycle.yml roles/ tasks/
ansible-playbook -i localhost, lifecycle.yml --syntax-check -e @cloud.yml.example
git diff --check
```

语法检查出现 `lifecycle_target` 未匹配的提示是因为动态主机尚未生成。
测试必须保持离线，使用临时目录、测试令牌和模拟 API；不得因为测试调用真实云 API。
连接方式、handler 顺序、资源所有权或凭据处理发生变更时，增加能复现问题的回归测试。
普通文档和清理改动不需要添加镜像实现的测试。

默认以离线检查验证代码。真实 `./server up` / `down` 会产生费用或销毁磁盘，仅在用户
任务已授权对应云操作时运行。不要用生命周期的 `--check`、`--start-at-task` 或跳过步骤
代替安全验证。当前任务若只是审查、清理或写文档，不应改变服务器运行状态。

## 文件清理

清理限于确认可再生的 Python 字节码、Ansible 本机缓存和本任务生成的临时文件。
保留本机配置、加密 Vault、私钥、Nix 锁文件及开发环境。`.agents`、`.codex`、`.aws`
可能是运行环境挂载，不要移动或清空。检查并保留用户已有的未提交改动，尤其是
`roles/searxng/templates/settings.yml.j2`。不要擅自提交、重置或覆盖工作区。
