import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
vault_options = runpy.run_path(str(ROOT / "server"))["vault_options"]


class VaultTests(unittest.TestCase):
    def test_up_uses_password_helper_without_password_in_arguments(self):
        options = vault_options("up", [], {"ANSIBLE_VAULT_PASSWORD": "test-only-password"}, ROOT)
        self.assertEqual(options, ["--vault-password-file", str(ROOT / "scripts/vault-password")])
        self.assertNotIn("test-only-password", " ".join(options))

    def test_down_and_missing_password_do_not_use_helper(self):
        self.assertEqual(vault_options("down", [], {"ANSIBLE_VAULT_PASSWORD": "test"}, ROOT), [])
        self.assertEqual(vault_options("up", [], {}, ROOT), [])

    def test_explicit_vault_options_take_precedence(self):
        for options in (["--ask-vault-pass"], ["-J"], ["--vault-password-file", "other"],
                        ["--vault-id=dev@prompt"], ["--vault-password-file=other"]):
            with self.subTest(options=options):
                self.assertEqual(vault_options("up", options, {"ANSIBLE_VAULT_PASSWORD": "test"}, ROOT), [])
        for variable in ("ANSIBLE_VAULT_PASSWORD_FILE", "ANSIBLE_VAULT_IDENTITY_LIST"):
            self.assertEqual(vault_options("up", [], {"ANSIBLE_VAULT_PASSWORD": "test", variable: "other"}, ROOT), [])

    def test_helper_reads_environment_and_rejects_missing_or_multiline_password(self):
        for password in ("test-only-password", "", "two\nlines"):
            with self.subTest(valid=bool(password) and "\n" not in password):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/vault-password")],
                    env=dict(os.environ, ANSIBLE_VAULT_PASSWORD=password),
                    capture_output=True, text=True, check=False,
                )
                if password and "\n" not in password:
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, password + "\n")
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")

    @unittest.skipUnless(shutil.which("ansible-vault"), "requires Ansible")
    def test_ansible_can_encrypt_and_decrypt_using_environment_helper(self):
        with tempfile.TemporaryDirectory(prefix="vault-helper-test-") as tmp:
            path = Path(tmp) / "fixture.yml"
            contents = "test_value: offline-fixture\n"
            path.write_text(contents)
            env = dict(os.environ, ANSIBLE_VAULT_PASSWORD="test-only-vault-password",
                       ANSIBLE_VAULT_PASSWORD_FILE=str(ROOT / "scripts/vault-password"),
                       ANSIBLE_LOCAL_TEMP=str(Path(tmp) / "ansible-tmp"))
            for operation in ("encrypt", "view"):
                result = subprocess.run(
                    ["ansible-vault", operation, str(path)], env=env,
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                if operation == "view":
                    self.assertEqual(result.stdout, contents)


if __name__ == "__main__":
    unittest.main()
