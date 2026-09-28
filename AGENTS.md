# Repository guidance

This Ansible project deploys Debian 13 with Hysteria2, SearXNG, a localhost Nginx Host router, and Scramjet-App. Read `site.yml`, `group_vars/vultr/main.yml`, the relevant role, and `README.md` before changing deployment behavior. Existing worktree changes may be user-owned; preserve them.

## Architecture and boundaries

- Hysteria2 alone listens on public TCP 80/443 and UDP 443 plus the configured port hopping range. It owns ACME/TLS and forwards masquerade HTTP to `127.0.0.1:8081` with `rewriteHost: false`.
- Nginx listens only on `127.0.0.1:8081`, routes `s.oui.moe` to SearXNG `127.0.0.1:8080` and `web.oui.moe` to Scramjet `127.0.0.1:8082`, and returns 421 for unknown Hosts. WebVPN is publicly accessible without a password by user request.
- Do not publish 8080, 8081, or 8082; do not add another TLS terminator. Keep Scramjet's dedicated Docker subnet and Wisp/private-network restrictions.
- Search titles keep their original URLs. The `proxy` result link opens the WebVPN launcher in a new tab. Use the same `cache_link` class as SearXNG's adjacent `cached` link.
- Keep credentials in Ansible Vault. Never print Vault contents or commit unencrypted secrets.

## Upstream updates

The user's current policy is to fetch SearXNG `latest` and Scramjet-App `main` on each deployment. The playbook should still report `changed=0` if upstream content and local configuration have not changed.

`roles/searxng/files/render_macro.py` reads the current image's `simple/macros.html` and inserts one link. `roles/scramjet/files/render_integration.py` derives a minimal launcher and Wisp settings from the current checkout. These generators deliberately fail when expected upstream anchors change. Review the new upstream API and template before adapting an anchor; do not silently reuse an old full-file override. Do not modify SearXNG engine adapters or Scramjet/BareMux/Wisp core.

## Validation

Run `ansible-playbook site.yml --syntax-check`, `ansible-lint site.yml`, `git diff --check`, then `ansible-playbook site.yml --ask-vault-pass --check --diff`. For deployment, run the playbook twice and confirm the second recap has `changed=0` when upstream has not advanced. Nginx handlers must skip service actions in check mode and validate with `nginx -t` before reload.

After deployment verify `systemctl status`, both Compose stacks, `ss -lntup`, both domain certificates, Host routing (search 200, unauthenticated WebVPN 200, unknown Host 421), a live search with original title links and styled `proxy` links, Wisp WebSocket upgrade, and Wisp denial of loopback, metadata, Docker bridge, and RFC1918 targets. Test a public target as a positive control. The Nix LibreWolf package has shown its own “Blocked Page” for Scramjet frame navigation even when direct Scramjet access and Wisp work; Chrome and Safari were confirmed working by the user.
