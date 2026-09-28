# Vultr Debian 13：Hysteria2 + SearXNG + Scramjet WebVPN

本项目用 Ansible 部署：

```text
Hysteria2
├─ UDP 443,20000-50000 → Hysteria proxy
└─ TCP 80/443 HTTP/HTTPS masquerade（ACME/TLS）
        ↓ 127.0.0.1:8081
      Nginx Host router
      ├─ s.oui.moe   → 127.0.0.1:8080 SearXNG
      └─ web.oui.moe → 127.0.0.1:8082 Scramjet-App
```

`s.oui.moe` 是搜索入口。普通 HTTP/HTTPS 结果的标题仍直接指向原网站；结果下方的 `proxy` 链接在新标签打开 `https://web.oui.moe/?url=<encoded target>`。`web.oui.moe` 是无需密码的 Web proxy 入口。Nginx、SearXNG、Scramjet 只在宿主 loopback 发布端口；Nginx 不管理 TLS。未知 Host 返回 421。

## 部署准备

1. 将 `s.oui.moe` 和 `web.oui.moe` 的 A/AAAA 记录指向 Vultr 主机。
2. 在 Vultr Firewall 放行管理 SSH 端口、TCP 80/443、UDP 443/20000-50000。不要放行 8080/8081/8082。
3. 本机安装 Nix 并运行 `nix develop`，或自行安装 Ansible。
4. 从 `inventory/hosts.yml.example` 创建被 Git 忽略的 `inventory/hosts.yml`。
5. 从 `group_vars/vultr/vault.yml.example` 创建 Vault 文件，填写 `hysteria_auth_password` 和 `searxng_secret_key`，再运行 `ansible-vault encrypt group_vars/vultr/vault.yml`。明文密码不要写入仓库。
6. 按需调整 `group_vars/vultr/main.yml` 中的域名、ACME 邮箱及端口。

```bash
ansible-playbook site.yml --ask-vault-pass --check --diff
ansible-playbook site.yml --ask-vault-pass
ansible-playbook site.yml --ask-vault-pass
```

Hysteria 客户端仍连接 `s.oui.moe:443`，使用原有认证密码、开启 TLS 校验，并按需配置 `443,20000-50000` UDP port hopping。

## 更新策略

每次运行 Playbook 都会执行 `docker compose pull searxng`，使用 Docker Hub 的 `searxng/searxng:latest`，并将 Scramjet-App 的本地 checkout 更新到上游 `main`。如果上游内容未变，生成文件和容器不会因此无条件重建；上游更新时则更新相应容器。Hysteria 保留原有 `latest` 下载设置。

SearXNG 的 `ui.templates_path` 指向整棵主题树，不能单独叠加一个文件。[宏生成器](roles/searxng/files/render_macro.py) 从刚拉取的镜像读取当前 `simple/macros.html`，只加入普通结果的 `proxy` 链接，再单文件挂载回容器。Scramjet-App 上游 Dockerfile 当前引用仓库未包含的 `package-lock.json`；本项目用上游 `pnpm-lock.yaml` 构建。[集成生成器](roles/scramjet/files/render_integration.py) 从当前 checkout 生成两个应用层覆盖文件：`public/index.js` 加入 `?url=` 启动，`src/index.js` 配置 Wisp 私网限制，不修改 Scramjet/BareMux/Wisp core。

上游如果改动关键 macro 或导航接口，生成器会报错，避免把不兼容的旧覆盖文件套在新版本上。使用 `latest` 与 `main` 意味着每次部署可能引入新上游代码；部署后应重新执行主页、`?url=`、搜索结果、WebSocket、私网阻断和站点兼容性测试。查看 Scramjet 实际 commit：`git -C /opt/scramjet/source rev-parse HEAD`；查看 SearXNG 实际镜像：`docker image inspect searxng/searxng:latest --format '{{.Id}}'`。

## 访问控制与网络边界

`web.oui.moe` 不要求密码，任何能访问该域名的人都可以使用这台服务器的公网出口代理浏览。需要限制使用者时，应重新配置访问控制；Scramjet 的私网限制不能替代入口认证。

Scramjet/Wisp 显式禁用直接 IP、私网 IP 和 loopback IP 连接。Scramjet 在专用 Docker 子网 `172.30.82.0/24`，nftables 还阻断该子网到宿主服务、RFC1918、link-local/metadata 和其他保留 IPv4 网段的连接；其公网出口仍由既有 Docker NAT 提供。现有 SearXNG 网桥规则保持不变。Vultr 数据中心 IP 可能在某些站点遇到 CAPTCHA 或额外验证。

浏览器兼容性：用户已验证 Chrome 和 Safari 可使用 WebVPN。Nix 打包的 LibreWolf 在 Scramjet frame 导航时显示浏览器自身的 “Blocked Page” 提示；直连 Scramjet 且 service worker 已激活时仍可复现。此现象与服务器 Wisp 私网拦截不同。

## 检查与维护

```bash
ssh root@服务器 'systemctl status hysteria-server nginx docker --no-pager'
ssh root@服务器 'docker compose -f /opt/searxng/compose.yml ps'
ssh root@服务器 'docker compose -f /opt/scramjet/compose.yml ps'
ssh root@服务器 'docker compose -f /opt/scramjet/compose.yml logs --tail=100'
ssh root@服务器 'ss -lntup'
```

确认 8080/8081/8082 只绑定 `127.0.0.1`；公网仅有管理 SSH、TCP 80/443、UDP 443/20000-50000。检查两个域名证书 SAN、未知 Host 421、WebVPN 无密码访问 200、普通结果 `proxy` 链接、WebSocket upgrade 和 Hysteria 代理/跳端口。使用 Scramjet 尝试访问 `127.0.0.1`、`localhost`、`169.254.169.254`、Docker bridge 和宿主 SSH；均应失败。不要提交 Vault 明文、inventory 或私钥。
