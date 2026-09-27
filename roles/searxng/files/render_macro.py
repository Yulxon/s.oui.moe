#!/usr/bin/env python3
"""Overlay one SearXNG result macro from the currently pulled image."""

import html
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True)


def main():
    image, search_domain, proxy_domain, output = sys.argv[1:]
    source = run(
        "docker", "run", "--rm", "--network", "none", "--entrypoint", "cat",
        image, "/usr/local/searxng/searx/templates/simple/macros.html",
    )
    image_id = run("docker", "image", "inspect", "--format", "{{.Id}}", image).strip()
    macro_start = "{%- macro result_sub_footer(result) -%}"
    macro_end = "{%- endmacro -%}"
    start = source.find(macro_start)
    if start < 0:
        raise RuntimeError("SearXNG result_sub_footer macro changed; review latest upstream")
    end = source.find(macro_end, start)
    if end < 0:
        raise RuntimeError("SearXNG result_sub_footer macro has no end")
    section = source[start:end]
    anchor = "\n</div>{{- '' -}}"
    if section.count(anchor) != 1 or 'class="engines"' not in section:
        raise RuntimeError("SearXNG result footer structure changed; review latest upstream")
    # JSON string syntax is also valid Jinja string syntax and quotes domains safely.
    import json
    search_literal = json.dumps(search_domain)
    proxy_literal = json.dumps(proxy_domain)
    proxy_href = html.escape(proxy_domain, quote=True)
    insertion = (
        "\n  {%- if result.template == 'default.html' and "
        "result.parsed_url.scheme in ('http', 'https') and "
        f"result.parsed_url.hostname not in ({search_literal}, {proxy_literal}) %}}\n"
        f'  <a class="cache_link" href="https://{proxy_href}/?url={{{{ result.url | urlencode | e }}}}" '
        'target="_blank" rel="noopener noreferrer nofollow" '
        'referrerpolicy="no-referrer">proxy</a>\n'
        "  {%- endif %}"
    )
    source = source[:start] + section.replace(anchor, insertion + anchor) + source[end:]
    rendered = (
        "{# Based on SearXNG latest image " + image_id +
        "; modified only to add the WebVPN proxy launcher. #}\n" + source
    )
    dest = Path(output)
    if dest.exists() and dest.read_text() == rendered:
        print("ok")
        return
    with tempfile.NamedTemporaryFile(mode="w", dir=dest.parent, delete=False) as temp:
        temp.write(rendered)
        temp_name = temp.name
    os.chmod(temp_name, 0o644)
    os.replace(temp_name, dest)
    print("changed")


if __name__ == "__main__":
    main()
