# Vultr Debian 13：Hysteria2

本项目只部署 Hysteria2，域名为 `s.oui.moe`。Hysteria 管理 ACME/TLS，监听 TCP 80/443 和 UDP 443,20000-50000，HTTP 自动跳转 HTTPS，伪装反向代理到 `https://priv.au/`，并将 Host 改写为目标站点。

不再部署 SearXNG、Nginx 或 Scramjet，也不再申请 `web.oui.moe` 证书。迁移任务会移除两个旧 Compose 栈的容器和网络、停止并卸载 Nginx、移除旧部署定义及本项目的 Docker NAT 表。旧应用数据和镜像保留，其他 Docker 工作负载不受管理。

## 部署准备

1. 将 `s.oui.moe` 的 A/AAAA 记录指向 Vultr 主机。可在 DNS 管理端删除不再使用的 `web.oui.moe` 记录。
2. 在 Vultr Firewall 放行管理 SSH、TCP 80/443、UDP 443/20000-50000。
3. 运行 `nix develop`，或安装 Ansible 和 `requirements.yml` 中的集合。
4. 从 `inventory/hosts.yml.example` 创建被 Git 忽略的 `inventory/hosts.yml`。
5. 从 `group_vars/vultr/vault.yml.example` 创建 Vault 文件，填写 `hysteria_auth_password`，再运行 `ansible-vault encrypt group_vars/vultr/vault.yml`。已有 Vault 可继续使用；旧搜索密钥不再使用。
6. 按需调整 `group_vars/vultr/main.yml` 中的域名、ACME 邮箱、伪装 URL 及端口。

```bash
ansible-playbook site.yml --syntax-check
ansible-lint site.yml
git diff --check
ansible-playbook site.yml --ask-vault-pass --check --diff
ansible-playbook site.yml --ask-vault-pass
ansible-playbook site.yml --ask-vault-pass
```

上游未变化时第二次部署应为 `changed=0`。Hysteria 保留官方 `latest` 下载设置，可用固定 release URL 和 checksum 锁定版本。

客户端连接 `s.oui.moe:443`，使用原有认证密码、开启 TLS 校验，并按需配置 `443,20000-50000` UDP port hopping。

## IPv4 出站补充

此主机没有原生 IPv4 默认路由。`warp_enabled: true` 启用 Cloudflare 官方 Debian 13 WARP 客户端，使用 MASQUE 补充 IPv4 出站；`::/0` 排除规则保留原生 IPv6 和 SSH/Hysteria 入站回复，系统 DNS 不交给 WARP。WARP 在 Hysteria 部署之前配置，注册信息仅保留在服务器 `/var/lib/cloudflare-warp/`。安装禁用推荐包。

仅配置 WARP：`ansible-playbook site.yml --ask-vault-pass --tags warp`。首次注册自动接受 Cloudflare 客户端服务条款。WARP 出口为共享地址，不提供公网 IPv4 入站。

```bash
ssh -F /dev/null root@s.oui.moe 'warp-cli --accept-tos status'
ssh -F /dev/null root@s.oui.moe 'curl -4 -fsS https://www.cloudflare.com/cdn-cgi/trace'
ssh -F /dev/null root@s.oui.moe 'curl -6 -fsS https://www.cloudflare.com/cdn-cgi/trace'
```

IPv4 应显示 `warp=on`，IPv6 应显示 `warp=off`。临时回退可执行 `warp-cli --accept-tos disconnect` 并停止 `warp-svc`；同时将 `warp_enabled` 改为 `false` 防止重新部署开启，禁用变量本身不会卸载或停止已安装服务。

## 服务检查

```bash
ssh root@s.oui.moe 'systemctl status hysteria-server --no-pager'
ssh root@s.oui.moe 'docker ps; ss -lntup'
curl -I https://s.oui.moe/
```

确认 Hysteria 活跃、旧容器及 Nginx 已停止、8080/8081/8082 没有监听。检查 `s.oui.moe` 证书 SAN、HTTPS 伪装响应、HTTP 到 HTTPS 跳转及 Hysteria 代理/跳端口。证书缓存中旧域名文件可能仍存在，但配置只申请 `s.oui.moe`。不要提交 Vault 明文、inventory 或私钥。

如果主机预装并启用了 UFW，本项目会同时为 UFW 添加所需端口规则，保持 UFW 启用。仅在 nftables 中放行不能覆盖另一套防火墙的拒绝规则。ACME HTTP-01 要求域名所有有效 A/AAAA 地址的 TCP 80 可达；验证失败可能触发 Let’s Encrypt 限流，应修复网络后等待日志中的 retry-after 时间。Playbook 会等待 TCP 443 就绪，避免仅因 systemd 启动命令成功而误报部署成功。
