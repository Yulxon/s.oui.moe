# Vultr 按需双栈代理：Hysteria2 + SearXNG

用 `./server up` 创建或复用一台 Debian 13 Vultr 实例，配置 IPv4/IPv6、Cloudflare
A/AAAA，再部署 Hysteria2 和 SearXNG。用 `./server down` 删除受管理 DNS 并销毁实例。
域名、密码、SNI 和端口保持一致，mihomo 无需修改配置；IP 改变后需等待 DNS 缓存过期并重新连接。

## 服务结构

- Hysteria2：UDP `443,20000-50000`，支持端口跳跃和双栈；客户端保持证书校验开启。
- Web：同一域名的 TCP 80/443，由 Hysteria masquerade 反代到 SearXNG。
- SearXNG：Docker Compose，仅发布到 `127.0.0.1:8080`。
- 证书：默认 Cloudflare DNS-01 自动签发和续期，不依赖 HTTP 入站验证。
- 防火墙：nftables 限制入站端口，并保留 Docker、Hysteria 自行维护的规则。
  镜像若预装 UFW，会先应用项目规则再停用 UFW，避免它只放行 SSH 而阻断服务。

## 本地配置

安装支持 flakes 的 Nix 后进入开发环境：

```bash
nix develop
cp -n cloud.yml.example cloud.yml
cp -n .envrc.local.example .envrc.local
cp -n group_vars/vultr/vault.yml.example group_vars/vultr/vault.yml
chmod 600 cloud.yml .envrc.local group_vars/vultr/vault.yml
```

已有本机配置直接复用，不要覆盖。按下表填写：

| 配置 | 内容 |
| --- | --- |
| `group_vars/vultr/main.yml` | 固定域名、ACME 邮箱、时区、服务镜像和端口 |
| `cloud.yml` | Vultr 区域、套餐、Debian 13 x64 OS ID、SSH Key UUID、对应私钥路径、Cloudflare Zone ID |
| `group_vars/vultr/vault.yml` | Hysteria 密码（至少 16 字符）和 SearXNG 密钥（至少 32 字符） |
| `.envrc.local` | `VULTR_API_KEY`、`CLOUDFLARE_API_TOKEN`，以及可选的 `ANSIBLE_VAULT_PASSWORD` |

生成随机值可用 `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`。
**先填写 Vault，再加密**；已有加密文件使用 `ansible-vault edit`，不要重新生成密码：

```bash
ansible-vault encrypt group_vars/vultr/vault.yml
```

SSH 公钥必须先上传到 Vultr。`vultr_ssh_key_ids` 需要 API 返回的 UUID，不能填写
`id_ed25519` 这样的名称、本地路径或指纹。OS ID 和 SSH Key UUID 可分别通过
`GET /v2/os`、`GET /v2/ssh-keys` 查询。

Vultr API 需允许控制端公网 IP。若返回 `Unauthorized IP address`，在 Vultr 的
Account → API → Access Control 中添加错误消息里的出口 IP；使用代理/VPN 时，
该地址可能与本机直连公网 IP 不同，不需要因此重建实例或更换密钥。
Cloudflare Token 需要 Zone Read 和 DNS Edit，并允许
控制端及服务器访问 Cloudflare API。若附加 Vultr Firewall Group，对 IPv4/IPv6 均需
放行 TCP 22/80/443、UDP 443/20000-50000，以及 IPv6 ICMP。生命周期使用 root SSH/22。

## 日常开启与关闭

`.envrc` 会加载被 Git 忽略的 `.envrc.local`。首次或修改加载规则后运行 `direnv allow`。
配置 `ANSIBLE_VAULT_PASSWORD` 后：

```bash
./server up
./server down
```

未保存 Vault 密码时使用 `./server up --ask-vault-pass`，也可以传入
`--vault-password-file /安全路径/password` 或 `--vault-id`；显式选项优先。
环境变量密码通过 `scripts/vault-password` 交给 Ansible，不进入命令参数。
`.envrc.local` 是本机明文凭据文件，应保持 `0600`；`down` 不需要 Vault 密码。

`up` 会先校验 Vault、SSH 私钥和资源所有权。新实例同时启用 IPv4、IPv6；已有
IPv4-only 实例会补开 IPv6、通过 Vultr API 重启一次，并配置 Debian 持久网络。
DNS A/AAAA 强制灰云、TTL 60 秒。部署失败后保留实例，修复配置后重跑 `up` 可复用它。
本机解析结果仅作诊断：缓存、代理 Fake-IP 或 AAAA 重写导致的差异会显示实际与预期地址，
不阻止按 IP 部署和 DNS-01 签证书。客户端仍需能解析到正确地址，必要时清理 DNS 缓存、
重启 mihomo，或检查本地 DNS/代理规则。

`down` 会**销毁实例及磁盘**。Vultr 单纯关机仍会计费；此流程不清理独立快照、备份等资源。
本机 Vault 和配置会保留。正常创建的资源都带有管理标记，后续无需手动接管。

## 资源接管与并发

实例必须同时匹配 `lifecycle_label` 和 `lifecycle_tag`；DNS 删除只针对 comment 与
本流程标记一致的记录。发现重复实例、名称冲突或查询结果不完整时停止操作。

首次迁移已有服务器时，确认身份后手动设置匹配的 label/tag。已有单条 A/AAAA 可通过
临时设置 `adopt_existing_dns: true` 接管；迁移后改回 `false`。同名 CNAME、重复 A/AAAA
需先清理。`down` 会保留未接管的 DNS，并报告删除与保留数量；删除 0 个实例意味着
未找到受管理实例，不能据此认为旧服务器已经停止计费。

同一 checkout 由 `.lifecycle.lock` 防止并发。不要同时从其他 checkout 或机器执行。
创建请求不会自动重试；请求超时后先在 Vultr 确认结果，待实例可被查询后再重跑。
状态轮询会重试临时网络错误、非 JSON 或不完整响应；耗尽后保留实例，并显示脱敏的 HTTP 状态和 API 错误。
生命周期不支持 `--check`，也不要通过 `--start-at-task` 等选项跳过前置步骤。

## 证书与运行检查

Cloudflare Token 会写入服务器的 `/etc/hysteria/config.yaml`（仅 root 可读），供续期使用。
Hysteria 和 SearXNG 的密钥配置任务禁止日志与 diff。可在加密 Vault 中设置
`hysteria_cloudflare_api_token` 覆盖环境变量；显式设置 `hysteria_acme_type: http` 才启用
HTTP-01，此时公网 TCP/80 必须能完成验证。

ACME HTTP 429 应先修复验证问题，再等待日志给出的 retry-after；不要反复重启、删除
账户数据或换账户。服务失败重试间隔为 5 分钟。DNS-01 不绕过 CA 限额；当前每次重建
仍重新申请证书，频繁重建需要另行实现加密保存和恢复证书。

```bash
ssh root@你的域名 'systemctl status docker hysteria-server --no-pager'
ssh root@你的域名 'journalctl -u hysteria-server -n 80 --no-pager'
ssh root@你的域名 'docker compose -f /opt/searxng/compose.yml logs --tail=80'
```

生命周期 SSH 使用 `HostKeyAlias=vultr-实例UUID` 和首次信任的 `accept-new`，避免 IP 复用
与旧密钥冲突。手动按域名连接时会使用独立的 known_hosts 记录，应核对主机指纹。

部署后先检查服务器内部 IPv4 HTTPS、自身 IPv6 HTTPS 和 IPv6 路由，再单独检查控制端
到公网 IPv4 HTTPS。公网检查禁用 curl 的代理设置，短暂重试后会报告实际 curl 错误；
服务器内部通过而公网超时，意味着需要排查直连路由或 TCP/443 过滤，并非仍在等待证书。
公网不可达仍会使检查失败，不会静默跳过。以上不等于外部 IPv6 或 Hysteria UDP 连通，
需另用具有 IPv6 网络的 mihomo 客户端验证。

## 手动部署已有服务器

不管理云资源时，复制 `inventory/hosts.yml.example` 为 `inventory/hosts.yml`，填写 IP、
SSH 用户与私钥。DNS、双栈网络和上游防火墙由你事先配置；仍需准备 Vault 和 ACME 令牌。

```bash
ansible-playbook site.yml --ask-vault-pass
```

直接运行 Ansible 时，可设置 `ANSIBLE_VAULT_PASSWORD_FILE="$PWD/scripts/vault-password"`
复用环境变量密码。维护时可检查差异；新主机的 `--check` 不保证能验证尚未安装的软件。

## 开发与维护

`site.yml` 按 `common` → `searxng` → `hysteria` 部署；`lifecycle.yml` 通过动态 inventory
调用它。详细维护约定见 [AGENTS.md](AGENTS.md)。仅用 Ansible 内置模块，无需额外 collections。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
ansible-lint site.yml lifecycle.yml roles/ tasks/
ansible-playbook -i localhost, lifecycle.yml --syntax-check -e @cloud.yml.example
```

测试使用离线模拟 API 和临时目录，不操作真实云资源。镜像与二进制默认跟随 latest；
需要可重复版本时设置 `searxng_image`、固定版本的 `hysteria_download_base_url` 和
`hysteria_download_checksum`。不要提交实际 inventory、Vault、API Token、密码或私钥。

## IPv4 出站

此主机可选启用 Cloudflare WARP，为没有原生 IPv4 默认路由的环境补充 IPv4 出站；原生
IPv6 和入站连接保持独立。设置 `warp_enabled: true` 后，角色会在 Hysteria 部署前安装并
配置 WARP。WARP 使用共享出口地址，不提供公网 IPv4 入站；注册信息保留在服务器本机。
首次注册会接受 Cloudflare 客户端服务条款。

```bash
ssh -F /dev/null root@你的域名 'warp-cli --accept-tos status'
ssh -F /dev/null root@你的域名 'curl -4 -fsS https://www.cloudflare.com/cdn-cgi/trace'
ssh -F /dev/null root@你的域名 'curl -6 -fsS https://www.cloudflare.com/cdn-cgi/trace'
```

检查 IPv4 输出 `warp=on`、IPv6 输出 `warp=off`。禁用变量不会卸载已安装的服务；回退时需在
服务器运行 `warp-cli --accept-tos disconnect` 并停止 `warp-svc`。
