# Repository guidance

This Ansible project deploys Debian 13 with Hysteria2 only on `s.oui.moe`. Read `site.yml`, `group_vars/vultr/main.yml`, the relevant role, and `README.md` before changing deployment behavior. Preserve existing worktree changes.

## Architecture and boundaries

- Hysteria2 alone listens on public TCP 80/443 and UDP 443 plus the configured port hopping range. It owns ACME/TLS and proxies masquerade HTTP to `https://priv.au/` with `rewriteHost: true` and `xForwarded: false`.
- ACME requests only `s.oui.moe`. Do not deploy `web.oui.moe`, SearXNG, Nginx, or Scramjet, or publish ports 8080/8081/8082.
- `retire_web` removes legacy Compose containers/networks and Nginx. Retain application data and images; do not remove unrelated Docker workloads.
- Keep credentials in Ansible Vault. Never print Vault contents or commit unencrypted secrets. Suppress Hysteria configuration diffs because they contain the authentication password.
- Historical web roles remain unused. Do not modify SearXNG engine adapters or Scramjet/BareMux/Wisp core.

## Validation

Run `ansible-playbook site.yml --syntax-check`, `ansible-lint site.yml`, `git diff --check`, then `ansible-playbook site.yml --ask-vault-pass --check --diff`. For deployment, run the playbook twice and confirm the second recap has `changed=0` when upstream has not advanced. Service handlers must skip actions in check mode.

After deployment verify Hysteria systemd status, `ss -lntup`, the `s.oui.moe` certificate, HTTP-to-HTTPS redirection, the HTTPS masquerade response, and authenticated proxy connectivity. Confirm retired containers/Nginx and loopback listeners 8080/8081/8082 are absent. Hysteria uses the official latest stable download unless explicitly pinned.
