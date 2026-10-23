"""Verify delegation uses the control machine without opening SSH connections."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = '''
import json, os
from pathlib import Path
from ansible.plugins.action import ActionBase
class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        with Path(os.environ['HEALTH_PROBE_EVENTS']).open('a') as out:
            out.write(json.dumps({'transport': self._connection.transport,
                                  'argv': self._task.args['argv']}) + '\\n')
        if self._connection.transport == 'local' and os.environ.get('HEALTH_PUBLIC_FAIL') == '1':
            return {'changed': False, 'rc': 28, 'stdout': 'HTTP=000',
                    'stderr': 'test connection timeout'}
        return {'changed': False, 'rc': 0}
'''


class HealthcheckTests(unittest.TestCase):
    def run_health_checks(self, public_failure=False):
        with tempfile.TemporaryDirectory(prefix='healthcheck-test-') as tmp:
            path = Path(tmp)
            plugins = path / 'plugins'
            plugins.mkdir()
            (plugins / 'health_probe.py').write_text(PROBE)
            source = (ROOT / 'lifecycle.yml').read_text()
            health_play = source.split('- name: Verify public HTTPS after deployment', 1)[1]
            (path / 'health.yml').write_text(
                '- name: Verify public HTTPS after deployment' +
                health_play.replace('ansible.builtin.command:', 'health_probe:')
            )
            (path / 'inventory.json').write_text(json.dumps({'all': {'children': {
                'lifecycle_target': {'hosts': {'lifecycle_server': {
                    'ansible_host': '203.0.113.10', 'ansible_connection': 'ssh',
                    'public_domain': 'test.example.com', 'lifecycle_ipv6_address': '2001:db8::10',
                }}},
                # An explicit localhost inventory entry defaults to SSH unless overridden.
                'control': {'hosts': {'localhost': {'ansible_connection': 'ssh'}}},
            }}}))
            (path / 'ansible.cfg').write_text('[defaults]\nretry_files_enabled=False\n')
            events = path / 'events.jsonl'
            env = dict(os.environ, ANSIBLE_CONFIG=str(path / 'ansible.cfg'),
                       ANSIBLE_ACTION_PLUGINS=str(plugins),
                       ANSIBLE_LOCAL_TEMP=str(path / 'ansible-tmp'),
                       HEALTH_PROBE_EVENTS=str(events), HEALTH_PUBLIC_FAIL='1' if public_failure else '0')
            result = subprocess.run(
                ['ansible-playbook', '-i', 'inventory.json', 'health.yml',
                 '-e', 'lifecycle_public_https_retries=1', '-e', 'lifecycle_public_https_delay=0'],
                cwd=path, env=env, capture_output=True, text=True, check=False,
            )
            output = result.stdout + result.stderr
            if public_failure:
                self.assertNotEqual(result.returncode, 0, output)
            else:
                self.assertEqual(result.returncode, 0, output)
            calls = [json.loads(line) for line in events.read_text().splitlines()]
            return calls, output

    def test_server_checks_are_remote_and_public_ipv4_check_is_local(self):
        calls, _ = self.run_health_checks()
        self.assertEqual([c['transport'] for c in calls], ['ssh', 'ssh', 'local'])
        self.assertIn('test.example.com:443:127.0.0.1', calls[0]['argv'])
        self.assertIn('test.example.com:443:[2001:db8::10]', calls[1]['argv'])
        self.assertIn('test.example.com:443:203.0.113.10', calls[2]['argv'])
        for call in calls:
            self.assertNotIn('--insecure', call['argv'])
            self.assertIn('--noproxy', call['argv'])

    def test_public_timeout_does_not_masquerade_as_a_certificate_failure(self):
        calls, output = self.run_health_checks(public_failure=True)
        self.assertEqual([c['transport'] for c in calls[:2]], ['ssh', 'ssh'])
        self.assertTrue(all(c['transport'] == 'local' for c in calls[2:]))
        self.assertIn('Server-side IPv4 and IPv6 HTTPS checks passed', output)
        self.assertIn('curl exit 28', output)
        self.assertIn('test connection timeout', output)
        self.assertIn('Certificate issuance is no longer the pending step', output)


if __name__ == '__main__':
    unittest.main()
