"""Render the real Hysteria role offline, including secret handling."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'test-only-"cloudflare\\token'
PASSWORD = 'test-only-password-"quoted\\value'
MOCK = '''
from ansible.plugins.action import ActionBase
class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        return {'changed': False}
'''


class AcmeTests(unittest.TestCase):
    def render_role(self, mode, token, expected=0):
        with tempfile.TemporaryDirectory(prefix='acme-role-test-') as tmp:
            path = Path(tmp)
            role = path / 'roles/hysteria'
            shutil.copytree(ROOT / 'roles/hysteria', role)
            (path / 'systemd').mkdir()
            for file in (role / 'tasks/main.yml', role / 'handlers/main.yml'):
                content = file.read_text().replace('ansible.builtin.systemd:', 'mock_service:')
                content = content.replace('ansible.builtin.get_url:', 'mock_service:')
                content = content.replace('/etc/hysteria', str(path / 'config'))
                content = content.replace('/etc/systemd/system', str(path / 'systemd'))
                content = content.replace('owner: root', f'owner: {os.getuid()}')
                content = content.replace('group: root', f'group: {os.getgid()}')
                file.write_text(content)
            plugins = path / 'plugins'
            plugins.mkdir()
            (plugins / 'mock_service.py').write_text(MOCK)
            config_path = path / 'config/config.yaml'
            variables = {
                'hysteria_acme_type': mode, 'hysteria_listen_ports': '443,20000-50000',
                'public_domain': 'test.example.com', 'acme_email': 'test@example.com',
                'hysteria_auth_password': PASSWORD, 'hysteria_arch': 'amd64',
                'hysteria_download_base_url': 'https://example.invalid',
                'searxng_bind_address': '127.0.0.1', 'searxng_port': 8080,
                'expected_token': token,
            }
            assertions = [
                'rendered.acme.type == hysteria_acme_type',
                'rendered.auth.password == hysteria_auth_password',
            ]
            if mode == 'dns':
                assertions += ['rendered.acme.dns.name == "cloudflare"',
                               'rendered.acme.dns.config.cloudflare_api_token == expected_token']
            else:
                assertions += ['"dns" not in rendered.acme']
            play = [{
                'name': 'Test real Hysteria configuration', 'hosts': 'localhost',
                'connection': 'local', 'gather_facts': False, 'vars': variables,
                'roles': ['hysteria'], 'tasks': [{
                    'name': 'Validate rendered YAML',
                    'ansible.builtin.assert': {'that': assertions},
                    'vars': {'rendered': "{{ lookup('file', '" + str(config_path) + "') | from_yaml }}"},
                    'no_log': True,
                }],
            }]
            (path / 'play.json').write_text(json.dumps(play))
            (path / 'ansible.cfg').write_text('[defaults]\nretry_files_enabled=False\n')
            env = dict(os.environ, ANSIBLE_CONFIG=str(path / 'ansible.cfg'),
                       ANSIBLE_ACTION_PLUGINS=str(plugins), ANSIBLE_LOCAL_TEMP=str(path / 'ansible-tmp'),
                       CLOUDFLARE_API_TOKEN=token)
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', 'play.json', '--diff'],
                                    cwd=path, env=env, capture_output=True, text=True)
            output = result.stdout + result.stderr
            self.assertNotIn(TOKEN, output)
            self.assertNotIn(PASSWORD, output)
            if expected == 0:
                self.assertEqual(result.returncode, 0, output)
                self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
                self.assertIn('RestartSec=300s', (path / 'systemd/hysteria-server.service').read_text())
            else:
                self.assertNotEqual(result.returncode, 0, output)
                self.assertFalse(config_path.exists())

    def test_dns01_renders_cloudflare_config_without_secret_diffs(self):
        self.render_role('dns', TOKEN)

    def test_http01_override_does_not_require_or_render_dns_token(self):
        self.render_role('http', '')

    def test_dns01_rejects_missing_credentials_before_writing_files(self):
        self.render_role('dns', '', expected=1)


if __name__ == '__main__':
    unittest.main()
