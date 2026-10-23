"""Execute real lifecycle tasks with offline API/connection adapters.

Run inside nix develop: python3 -m unittest discover -s tests -v
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OWNER = "ansible-lifecycle:ansible-hysteria-managed:ansible-hysteria"
SSH_KEY_ID = "11111111-2222-4333-8444-555555555555"
INSTANCE = {
    "id": "test-instance", "label": "ansible-hysteria",
    "tags": ["ansible-hysteria-managed"], "main_ip": "203.0.113.10",
    "v6_main_ip": "2001:db8::10", "v6_network_size": 64,
    "status": "active", "power_status": "running", "server_status": "ok",
}
RECORD = {"id": "test-record", "type": "A", "comment": OWNER}

API_ADAPTER = '''
import json
import os
from pathlib import Path
from ansible.plugins.action import ActionBase

class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        args = self._task.args
        url = args['url']
        method = args.get('method', 'GET')
        state_path = Path(os.environ['MOCK_STATE'])
        state = json.loads(state_path.read_text())
        with Path(os.environ['MOCK_EVENTS']).open('a') as events:
            events.write(json.dumps({'url': url, 'method': method,
                                     'body': args.get('body')}) + '\\n')
        if method == 'GET' and '/instances/' in url:
            if state.get('poll_responses'):
                result = state['poll_responses'].pop(0)
                state_path.write_text(json.dumps(state))
                return dict(changed=False, **result)
            if state.get('poll_failure'):
                return dict(changed=False, **state['poll_failure'])
        if '/dns_records' in url:
            if method == 'GET':
                if state.get('dns_lookup_status', 200) != 200:
                    return {'changed': False, 'status': state['dns_lookup_status'],
                            'json': {'success': False, 'errors': [{'message': 'Invalid token test-token'}],
                                     'private_data': 'MUST-NOT-BE-PRINTED'}}
                body = {'success': True, 'result': state['records'],
                        'result_info': {'total_count': len(state['records'])}}
            else:
                body = {'success': True}
            status = 200
        elif method == 'PATCH':
            state['instance']['v6_main_ip'] = '2001:db8::10'
            state_path.write_text(json.dumps(state))
            body, status = {'instance': state['instance']}, 202
        elif url.endswith('/reboot'):
            body, status = {}, 204
        elif method == 'POST':
            status = state.get('create_status', 202)
            body = ({'instance': state['instance']} if status == 202
                    else {'error': state.get('create_error', 'Invalid request'),
                          'default_password': 'MUST-NOT-BE-PRINTED'})
            if status == -1:
                body = {}
        elif method == 'DELETE':
            state['deleted'] = True
            state_path.write_text(json.dumps(state))
            body, status = {}, 204
        elif '/instances?' in url:
            if state.get('instance_lookup_status', 200) != 200:
                return {'changed': False, 'status': state['instance_lookup_status'],
                        'json': {'error': state.get('instance_lookup_error', 'Unauthorized'),
                                 'private_data': 'MUST-NOT-BE-PRINTED'}}
            body = {'instances': state['instances'],
                    'meta': {'total': len(state['instances']), 'links': {'next': ''}}}
            status = 200
        elif state.get('deleted'):
            body, status = {}, 404
        else:
            body, status = {'instance': state['instance']}, 200
        return {'changed': method != 'GET', 'status': status, 'json': body}
'''
READY_ADAPTER = '''
import json
import os
from ansible.plugins.action import ActionBase
class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        if any('scripts/check-dns' in str(arg) for arg in self._task.args.get('argv', [])):
            return {'changed': False, 'rc': int(os.environ.get('MOCK_DNS_RC', '0')),
                    'stdout': json.dumps({'matches': False, 'records': {'AAAA': {
                        'expected': '2001:db8::10', 'addresses': ['2001:db8::99']}}})}
        return {'changed': False, 'rc': 0, 'stdout': '[]',
                'ansible_facts': {'default_ipv4': {'interface': 'ens3'}}}
'''


class LifecycleTests(unittest.TestCase):
    def run_lifecycle(self, action, instances=(), records=(), adopt=False, expected=0,
                      create_status=202, create_error='Invalid request', return_output=False,
                      ssh_key_ids=None, instance=None, poll_responses=(), poll_failure=None,
                      poll_retries=6, dns_rc=0, instance_lookup_status=200,
                      instance_lookup_error='Unauthorized', dns_lookup_status=200):
        with tempfile.TemporaryDirectory(prefix="ansible-lifecycle-test-") as tmp:
            path = Path(tmp)
            (path / "tasks").mkdir()
            (path / "group_vars/vultr").mkdir(parents=True)
            plugins = path / "plugins"
            plugins.mkdir()
            (plugins / "mock_cloud.py").write_text(API_ADAPTER)
            (plugins / "mock_ready.py").write_text(READY_ADAPTER)
            # Swap only external API/SSH/DNS adapters; execute all task conditions,
            # ownership checks, data selection and API request construction.
            for source in (ROOT / "tasks").glob("cloud-*.yml"):
                text = source.read_text().replace("ansible.builtin.uri:", "mock_cloud:")
                text = text.replace("ansible.builtin.wait_for_connection:", "mock_ready:")
                text = text.replace("ansible.builtin.wait_for:", "mock_ready:")
                text = text.replace("ansible.builtin.setup:", "mock_ready:")
                text = text.replace("ansible.builtin.copy:", "mock_ready:")
                text = text.replace("ansible.builtin.blockinfile:", "mock_ready:")
                text = text.replace("ansible.builtin.command:", "mock_ready:")
                (path / "tasks" / source.name).write_text(text)
            play = (ROOT / "lifecycle.yml").read_text().split(
                "\n- name: Run the existing deployment", 1
            )[0]
            (path / "lifecycle.yml").write_text(play)
            (path / "group_vars/vultr/main.yml").write_text(json.dumps({
                "public_domain": "test.example.com", "acme_email": "test@example.com",
                "admin_ssh_port": 22,
            }))
            (path / "group_vars/vultr/vault.yml").write_text(json.dumps({
                "hysteria_auth_password": "test-only-password-123456",
                "searxng_secret_key": "test-only-secret-" * 4,
            }))
            key = path / "test-key"
            key.touch()
            (path / "cloud.yml").write_text(json.dumps({
                "vultr_region": "lax", "vultr_plan": "test-plan", "vultr_os_id": 123,
                "vultr_ssh_key_ids": [SSH_KEY_ID] if ssh_key_ids is None else ssh_key_ids,
                "ssh_private_key_file": str(key),
                "cloudflare_zone_id": "a" * 32, "lifecycle_label": "ansible-hysteria",
                "lifecycle_tag": "ansible-hysteria-managed", "adopt_existing_dns": adopt,
            }))
            state = path / "state.json"
            state.write_text(json.dumps({"instances": list(instances),
                                         "records": list(records), "instance": instance or INSTANCE,
                                         "create_status": create_status, "create_error": create_error,
                                         "instance_lookup_status": instance_lookup_status,
                                         "instance_lookup_error": instance_lookup_error,
                                         "dns_lookup_status": dns_lookup_status,
                                         "poll_responses": list(poll_responses), "poll_failure": poll_failure}))
            events = path / "events.jsonl"
            events.touch()
            env = dict(os.environ, ANSIBLE_ACTION_PLUGINS=str(plugins),
                       VULTR_API_KEY="test-token", CLOUDFLARE_API_TOKEN="test-token",
                       MOCK_STATE=str(state), MOCK_EVENTS=str(events),
                       MOCK_DNS_RC=str(dns_rc),
                       ANSIBLE_LOCAL_TEMP=str(path / "ansible-tmp"),
                       ANSIBLE_NOCOLOR="1")
            # Avoid inheriting the real repository's inventory or SSH settings.
            (path / "ansible.cfg").write_text("[defaults]\nretry_files_enabled=False\n")
            env['ANSIBLE_CONFIG'] = str(path / "ansible.cfg")
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "lifecycle.yml", "-e",
                 f"lifecycle_action={action}", "-e", "lifecycle_poll_delay=0", "-e",
                 f"lifecycle_poll_retries={poll_retries}"],
                cwd=path, env=env, capture_output=True, text=True,
            )
            if expected == 0:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            else:
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = [json.loads(line) for line in events.read_text().splitlines()]
            return (calls, result.stdout + result.stderr) if return_output else calls

    def test_local_dns_mismatch_is_visible_without_blocking_deployment(self):
        calls, output = self.run_lifecycle('up', dns_rc=1, return_output=True)
        self.assertIn('Deployment continues by IP', output)
        self.assertIn('2001:db8::99', output)
        self.assertTrue(any(c['method'] == 'POST' and (c.get('body') or {}).get('type') == 'AAAA'
                            for c in calls))

    def test_broken_dns_diagnostic_still_fails(self):
        self.run_lifecycle('up', dns_rc=2, expected=1)

    def test_vultr_unauthorized_ip_is_visible_and_stops_all_mutations(self):
        for action in ('up', 'down'):
            with self.subTest(action=action):
                calls, output = self.run_lifecycle(
                    action, instance_lookup_status=401,
                    instance_lookup_error='Unauthorized IP address: 203.0.113.42 test-token',
                    expected=1, return_output=True,
                )
                self.assertIn('Vultr instance lookup failed (HTTP 401)', output)
                self.assertIn('Unauthorized IP address: 203.0.113.42 [REDACTED]', output)
                self.assertIn('proxy/VPN egress', output)
                self.assertNotIn('test-token', output)
                self.assertNotIn('MUST-NOT-BE-PRINTED', output)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['method'], 'GET')

    def test_cloudflare_auth_error_is_visible_and_stops_all_mutations(self):
        calls, output = self.run_lifecycle('up', dns_lookup_status=403, expected=1, return_output=True)
        self.assertIn('Cloudflare DNS lookup failed (HTTP 403)', output)
        self.assertIn('Invalid token [REDACTED]', output)
        self.assertNotIn('test-token', output)
        self.assertNotIn('MUST-NOT-BE-PRINTED', output)
        self.assertTrue(all(c['method'] == 'GET' for c in calls))

    def test_create_error_is_visible_without_leaking_credentials_or_retrying(self):
        calls, output = self.run_lifecycle(
            "up", create_status=400, create_error="Invalid SSH key test-token",
            expected=1, return_output=True,
        )
        self.assertIn("HTTP 400", output)
        self.assertIn("Invalid SSH key [REDACTED]", output)
        self.assertNotIn("test-token", output)
        self.assertNotIn("MUST-NOT-BE-PRINTED", output)
        creates = [c for c in calls if c["method"] == "POST" and "/instances" in c["url"]]
        self.assertEqual(len(creates), 1)
        self.assertFalse(any("/dns_records" in c["url"] and c["method"] != "GET" for c in calls))

    def test_provisioning_poll_recovers_from_missing_and_malformed_json(self):
        failures = [
            {'status': -1, 'failed': True},
            {'status': 502, 'content': '<html>MUST-NOT-BE-PRINTED test-token</html>'},
            {'status': 200, 'json': {}},
            {'status': 200, 'json': {'instance': None}},
            {'status': 200, 'json': {'instance': dict(INSTANCE, main_ip=None)}},
            {'status': 200, 'json': []},
            {'status': 503, 'json': {'instance': INSTANCE}},
        ]
        calls, output = self.run_lifecycle('up', poll_responses=failures,
                                           poll_retries=len(failures), return_output=True)
        polls = [c for c in calls if c['method'] == 'GET' and '/instances/' in c['url']]
        self.assertEqual(len(polls), len(failures) + 2)
        self.assertEqual(sum(c['method'] == 'POST' and c['url'].endswith('/instances') for c in calls), 1)
        self.assertNotIn('test-token', output)
        self.assertNotIn('MUST-NOT-BE-PRINTED', output)

    def test_dual_stack_poll_recovers_from_missing_json_and_ipv6(self):
        responses = [
            {'status': 200, 'json': {'instance': INSTANCE}},
            {'status': 502},
            {'status': 200, 'json': {'instance': dict(INSTANCE, v6_main_ip='')}},
            {'status': 200, 'json': {'instance': dict(INSTANCE, v6_main_ip=None)}},
        ]
        calls = self.run_lifecycle('up', poll_responses=responses)
        polls = [c for c in calls if c['method'] == 'GET' and '/instances/' in c['url']]
        self.assertEqual(len(polls), 5)

    def test_poll_exhaustion_reports_status_without_leaking_raw_response(self):
        calls, output = self.run_lifecycle(
            'up', poll_failure={'status': 503, 'content': 'test-token MUST-NOT-BE-PRINTED'},
            poll_retries=2, expected=1, return_output=True,
        )
        self.assertIn('provisioning polling failed (HTTP 503)', output)
        self.assertIn('The instance is retained', output)
        self.assertNotIn('test-token', output)
        self.assertNotIn('MUST-NOT-BE-PRINTED', output)
        self.assertFalse(any('/dns_records' in c['url'] and c['method'] != 'GET' for c in calls))
        self.assertEqual(sum(c['method'] == 'POST' and c['url'].endswith('/instances') for c in calls), 1)

    def test_dual_stack_poll_failure_reports_redacted_api_error(self):
        calls, output = self.run_lifecycle(
            'up', poll_responses=[{'status': 200, 'json': {'instance': INSTANCE}}],
            poll_failure={'status': 503, 'json': {'error': 'Unavailable test-token',
                                                'default_password': 'MUST-NOT-BE-PRINTED'}},
            poll_retries=1, expected=1, return_output=True,
        )
        self.assertIn('dual-stack readiness polling failed (HTTP 503)', output)
        self.assertIn('Unavailable [REDACTED]', output)
        self.assertNotIn('test-token', output)
        self.assertNotIn('MUST-NOT-BE-PRINTED', output)
        self.assertFalse(any('/dns_records' in c['url'] and c['method'] != 'GET' for c in calls))

    def test_ssh_key_name_is_rejected_before_creation(self):
        calls, output = self.run_lifecycle(
            "up", ssh_key_ids=["id_ed25519"], expected=1, return_output=True,
        )
        self.assertIn("vultr_ssh_key_ids requires Vultr UUIDs", output)
        self.assertTrue(all(c["method"] == "GET" for c in calls))

    def test_create_network_failure_stops_before_dns_changes(self):
        calls, output = self.run_lifecycle(
            "up", create_status=-1, expected=1, return_output=True,
        )
        self.assertIn("HTTP -1", output)
        self.assertIn("check the Vultr instance list before retrying", output)
        self.assertFalse(any("/dns_records" in c["url"] and c["method"] != "GET" for c in calls))

    def test_up_creates_instance_and_dns_without_changing_client_identity(self):
        calls = self.run_lifecycle("up")
        creates = [c for c in calls if c["method"] == "POST" and "/instances" in c["url"]]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["body"]["sshkey_id"], [SSH_KEY_ID])
        self.assertNotIn("firewall_group_id", creates[0]["body"])
        self.assertIs(creates[0]["body"]["enable_ipv6"], True)
        self.assertIs(creates[0]["body"]["disable_public_ipv4"], False)
        dns = [c for c in calls if c["method"] == "POST" and "/dns_records" in c["url"]][0]
        self.assertEqual(dns["body"]["name"], "test.example.com")
        self.assertEqual(dns["body"]["content"], INSTANCE["main_ip"])
        self.assertIs(dns["body"]["proxied"], False)
        dns6 = [c for c in calls if c["method"] == "POST" and "/dns_records" in c["url"]
                and c["body"]["type"] == "AAAA"]
        self.assertEqual(len(dns6), 1)
        self.assertEqual(dns6[0]["body"]["content"], INSTANCE["v6_main_ip"])

    def test_up_reuses_owned_instance(self):
        calls = self.run_lifecycle("up", [INSTANCE], [RECORD, dict(RECORD, id='ipv6-record', type='AAAA')])
        self.assertFalse(any(c["method"] == "POST" for c in calls))

    def test_up_enables_ipv6_and_reboots_existing_ipv4_instance(self):
        ipv4_only = dict(INSTANCE, v6_main_ip='')
        calls = self.run_lifecycle("up", [ipv4_only], [RECORD], instance=ipv4_only)
        patches = [c for c in calls if c['method'] == 'PATCH']
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]['body'], {'enable_ipv6': True})
        reboots = [c for c in calls if c['url'].endswith('/reboot')]
        self.assertEqual(len(reboots), 1)
        self.assertFalse(any(c['method'] == 'POST' and c['url'].endswith('/instances') for c in calls))

    def test_foreign_instance_blocks_creation_and_deletion(self):
        for action in ("up", "down"):
            with self.subTest(action=action):
                calls = self.run_lifecycle(action, [dict(INSTANCE, tags=[])], expected=1)
                self.assertTrue(all(c["method"] == "GET" for c in calls))

    def test_duplicate_instances_block_mutations(self):
        calls = self.run_lifecycle("up", [INSTANCE, INSTANCE], expected=1)
        self.assertTrue(all(c["method"] == "GET" for c in calls))

    def test_conflicting_ipv6_blocks_creation(self):
        calls = self.run_lifecycle("up", records=[dict(RECORD, type="AAAA", comment='foreign')], expected=1)
        self.assertTrue(all(c["method"] == "GET" for c in calls))

    def test_foreign_dns_requires_explicit_adoption(self):
        foreign = dict(RECORD, comment="another-owner")
        calls = self.run_lifecycle("up", records=[foreign], expected=1)
        self.assertTrue(all(c["method"] == "GET" for c in calls))
        self.run_lifecycle("up", records=[foreign], adopt=True)

    def test_down_does_not_adopt_foreign_dns(self):
        calls = self.run_lifecycle("down", [INSTANCE], [dict(RECORD, comment="foreign")],
                                   adopt=True)
        deletes = [c["url"] for c in calls if c["method"] == "DELETE"]
        self.assertEqual(len(deletes), 1)
        self.assertIn("/instances/test-instance", deletes[0])

    def test_down_preserves_existing_aaaa_without_blocking_instance_deletion(self):
        foreign_aaaa = {"id": "foreign-aaaa", "type": "AAAA"}
        calls = self.run_lifecycle("down", [INSTANCE], [RECORD, foreign_aaaa])
        deletes = [c["url"] for c in calls if c["method"] == "DELETE"]
        self.assertEqual(len(deletes), 2)
        self.assertIn("/dns_records/test-record", deletes[0])
        self.assertIn("/instances/test-instance", deletes[1])
        self.assertFalse(any("foreign-aaaa" in c["url"] for c in calls))

    def test_down_removes_owned_ipv6_and_preserves_other_records(self):
        for record_type in ("A", "AAAA", "CNAME"):
            with self.subTest(record_type=record_type):
                owned = dict(RECORD, type=record_type)
                foreign = {"id": "foreign-record", "type": record_type}
                calls = self.run_lifecycle("down", [INSTANCE], [owned, foreign])
                deletes = [c["url"] for c in calls if c["method"] == "DELETE"]
                self.assertEqual(len(deletes), 2)
                self.assertIn("/dns_records/test-record", deletes[0])
                self.assertFalse(any("foreign-record" in c["url"] for c in calls))

    def test_down_without_managed_resources_preserves_all_existing_dns(self):
        calls = self.run_lifecycle("down", records=[
            {"id": "old-a", "type": "A", "comment": None},
            {"id": "old-aaaa", "type": "AAAA"},
        ])
        self.assertTrue(all(c["method"] == "GET" for c in calls))

    def test_down_removes_dns_before_destroy_and_confirms_deletion(self):
        calls = self.run_lifecycle("down", [INSTANCE], [RECORD])
        deletes = [c["url"] for c in calls if c["method"] == "DELETE"]
        self.assertIn("/dns_records/test-record", deletes[0])
        self.assertIn("/instances/test-instance", deletes[1])
        self.assertEqual(calls[-1]["method"], "GET")
        self.assertIn("/instances/test-instance", calls[-1]["url"])

    def test_down_on_absent_resources_is_noop(self):
        calls = self.run_lifecycle("down")
        self.assertTrue(all(c["method"] == "GET" for c in calls))


if __name__ == "__main__":
    unittest.main()
