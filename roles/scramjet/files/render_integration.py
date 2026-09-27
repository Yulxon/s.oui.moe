#!/usr/bin/env python3
"""Add only launcher and Wisp access options to current Scramjet-App files."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

LAUNCHER = '''
// WebVPN ?url= integration; navigation remains in Scramjet-App's submit handler.
const requestedUrl = new URLSearchParams(location.search).get("url");
if (requestedUrl !== null) {
    try {
        const target = new URL(requestedUrl);
        if (!["http:", "https:"].includes(target.protocol) || !target.hostname) {
            throw new Error("Only HTTP and HTTPS URLs are supported.");
        }
        address.value = target.href;
        form.requestSubmit();
    } catch (err) {
        error.textContent = "Invalid proxy URL.";
        errorCode.textContent = err.toString();
    }
}
'''


def write_if_changed(path, content):
    if path.exists() and path.read_text() == content:
        return False
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temp:
        temp.write(content)
        temp_name = temp.name
    os.chmod(temp_name, 0o644)
    os.replace(temp_name, path)
    return True


def main():
    source, output = (Path(arg) for arg in sys.argv[1:])
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    client = (source / "public/index.js").read_text()
    server = (source / "src/index.js").read_text()
    required_client = (
        "const { ScramjetController } = $scramjetLoadController();",
        'form.addEventListener("submit", async (event) => {',
        "frame.go(url);",
    )
    if any(marker not in client for marker in required_client) or "const requestedUrl" in client:
        raise RuntimeError("Scramjet client navigation changed; review latest upstream")
    if "Object.assign(wisp.options, {" not in server or "wisp.routeRequest" not in server:
        raise RuntimeError("Scramjet Wisp server changed; review latest upstream")
    if any(option in server for option in (
        "allow_direct_ip:", "allow_private_ips:", "allow_loopback_ips:"
    )):
        raise RuntimeError("Upstream now configures Wisp IP policy; review before deploying")
    server = server.replace("\thostname_blacklist: [/example\\.com/],\n", "")
    if "hostname_blacklist:" in server:
        raise RuntimeError("Upstream Wisp hostname policy changed; review before deploying")
    server = server.replace(
        "Object.assign(wisp.options, {",
        "Object.assign(wisp.options, {\n"
        "\tallow_direct_ip: false,\n"
        "\tallow_private_ips: false,\n"
        "\tallow_loopback_ips: false,\n"
        "\thostname_blacklist: [/^localhost$/i, /\\.localhost$/i],",
        1,
    )
    client = client.rstrip() + "\n" + LAUNCHER
    client = f"// Based on Scramjet-App {revision}; adds only the ?url= launcher.\n" + client
    server = f"// Based on Scramjet-App {revision}; adds only Wisp access policy.\n" + server
    changed = write_if_changed(output / "launcher.js", client)
    changed = write_if_changed(output / "index.js", server) or changed
    print("changed" if changed else "ok")


if __name__ == "__main__":
    main()
