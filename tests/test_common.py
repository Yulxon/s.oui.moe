"""Run common-role ordering with an offline service manager."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = '''
import json, os
from pathlib import Path
from ansible.plugins.action import ActionBase
class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        args = self._task.args
        services = {'nftables.service': {}}
        if os.environ['MOCK_DOCKER'] == '1':
            services['docker.service'] = {}
        if os.environ.get('MOCK_UFW'):
            services['ufw.service'] = {}
        with Path(os.environ['MOCK_COMMON_EVENTS']).open('a') as out:
            out.write(json.dumps(args) + '\\n')
        if not args:
            return {'changed': False, 'ansible_facts': {'services': services}}
        if args.get('state') in ['restarted', 'reloaded', 'started']:
            name = args.get('name', '')
            if name.removesuffix('.service') + '.service' not in services:
                return {'failed': True, 'msg': 'Service not installed: ' + name}
        command = args.get('cmd', args.get('_raw_params', ''))
        stdout = ('Status: ' + os.environ['MOCK_UFW']) if command == 'ufw status' else 'America/Los_Angeles'
        changed = 'dest' in args or 'state' in args
        if args.get('dest') == '/etc/nftables.conf':
            changed = os.environ.get('MOCK_FIREWALL_CHANGED', '1') == '1'
        return {'changed': changed, 'rc': 1 if command.startswith('nft delete') else 0,
                'stdout': stdout}
'''


class CommonRoleTests(unittest.TestCase):
    def run_common(self, docker, ufw='', firewall_changed=True):
        with tempfile.TemporaryDirectory(prefix='common-role-test-') as tmp:
            path = Path(tmp)
            (path / 'plugins').mkdir()
            (path / 'plugins/mock_common.py').write_text(ADAPTER)
            def adapt(text):
                text = re.sub(r'(?m)^(\s*)ansible.builtin.command: ([^\n]+)$',
                              r'\1ansible.builtin.command:\n\1  cmd: \2', text)
                for module in ('apt', 'service_facts', 'command', 'copy', 'systemd'):
                    text = text.replace(f'ansible.builtin.{module}:', 'mock_common:')
                return text
            (path / 'tasks.yml').write_text(adapt((ROOT / 'roles/common/tasks/main.yml').read_text()))
            handlers = adapt((ROOT / 'roles/common/handlers/main.yml').read_text())
            handlers += adapt((ROOT / 'roles/hysteria/handlers/main.yml').read_text()).removeprefix('---\n')
            (path / 'handlers.yml').write_text(handlers)
            (path / 'play.json').write_text(json.dumps([{
                'name': 'Test first deployment service ordering', 'hosts': 'localhost',
                'connection': 'local', 'gather_facts': False,
                'vars': {'common_base_packages': [], 'timezone': 'America/Los_Angeles',
                         'admin_ssh_port': 22, 'hysteria_listen_ports': '443,20000-50000'},
                'tasks': [{'ansible.builtin.import_tasks': 'tasks.yml'}],
                'handlers': [{'ansible.builtin.import_tasks': 'handlers.yml'}],
            }]))
            (path / 'ansible.cfg').write_text('[defaults]\nretry_files_enabled=False\n')
            events = path / 'events.jsonl'
            env = dict(os.environ, ANSIBLE_CONFIG=str(path / 'ansible.cfg'),
                       ANSIBLE_ACTION_PLUGINS=str(path / 'plugins'),
                       ANSIBLE_LOCAL_TEMP=str(path / 'ansible-tmp'),
                       MOCK_DOCKER='1' if docker else '0', MOCK_COMMON_EVENTS=str(events),
                       MOCK_UFW=ufw, MOCK_FIREWALL_CHANGED='1' if firewall_changed else '0')
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', 'play.json'],
                                    cwd=path, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return [json.loads(line) for line in events.read_text().splitlines()]

    def test_fresh_host_does_not_restart_uninstalled_services(self):
        calls = self.run_common(docker=False)
        self.assertFalse(any(c.get('name') in ['docker', 'hysteria-server.service'] for c in calls))
        self.assertTrue(any(c.get('name') == 'nftables' for c in calls))

    def test_existing_docker_restarts_after_firewall_reload(self):
        calls = self.run_common(docker=True)
        reload = next(i for i, c in enumerate(calls) if c.get('name') == 'nftables' and c.get('state') == 'reloaded')
        restart = next(i for i, c in enumerate(calls) if c.get('name') == 'docker' and c.get('state') == 'restarted')
        self.assertLess(reload, restart)
        self.assertFalse(any(c.get('name') == 'hysteria-server.service' for c in calls))

    def test_active_ufw_is_disabled_safely_when_config_is_unchanged(self):
        calls = self.run_common(docker=True, ufw='active', firewall_changed=False)
        apply = next(i for i, c in enumerate(calls) if c.get('cmd') == 'nft -f /etc/nftables.conf')
        disable = next(i for i, c in enumerate(calls) if c.get('cmd') == 'ufw --force disable')
        stop = next(i for i, c in enumerate(calls) if c.get('name') == 'ufw' and c.get('state') == 'stopped')
        restart = next(i for i, c in enumerate(calls) if c.get('name') == 'docker' and c.get('state') == 'restarted')
        self.assertLess(apply, disable)
        self.assertLess(disable, stop)
        self.assertLess(stop, restart)
        self.assertIs(calls[stop]['enabled'], False)

    def test_fresh_host_with_ufw_does_not_restart_uninstalled_docker(self):
        calls = self.run_common(docker=False, ufw='active')
        reload = next(i for i, c in enumerate(calls) if c.get('name') == 'nftables' and c.get('state') == 'reloaded')
        disable = next(i for i, c in enumerate(calls) if c.get('cmd') == 'ufw --force disable')
        self.assertLess(reload, disable)
        self.assertFalse(any(c.get('name') in ['docker', 'hysteria-server.service'] for c in calls))

    def test_inactive_ufw_does_not_run_the_disable_command(self):
        calls = self.run_common(docker=True, ufw='inactive', firewall_changed=False)
        self.assertFalse(any(c.get('cmd') == 'ufw --force disable' for c in calls))


if __name__ == '__main__':
    unittest.main()
