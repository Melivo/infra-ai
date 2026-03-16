from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import unittest


class StartScriptPythonEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = pathlib.Path(self._tmpdir.name)

        scripts_dir = self.repo_root / "scripts"
        scripts_dir.mkdir(parents=True)
        shutil.copy2(
            pathlib.Path(__file__).resolve().parents[1] / "scripts" / "start.sh",
            scripts_dir / "start.sh",
        )
        shutil.copy2(
            pathlib.Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.sh",
            scripts_dir / "bootstrap.sh",
        )

        (self.repo_root / "vllm").mkdir()
        (self.repo_root / "vllm" / ".env").write_text("HF_TOKEN=\n", encoding="utf-8")

        (self.repo_root / "requirements.txt").write_text(
            "questionary>=2,<3\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def run_start(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/start.sh", "--no-cli"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_start_fails_when_python_binary_is_missing(self) -> None:
        result = self.run_start()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python environment is not ready", result.stderr)
        self.assertIn("bash scripts/bootstrap.sh", result.stderr)

    def test_start_fails_when_requirements_stamp_is_missing(self) -> None:
        venv_bin = self.repo_root / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        python_bin = venv_bin / "python"
        python_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        python_bin.chmod(0o755)

        result = self.run_start()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python dependencies are not bootstrapped", result.stderr)
        self.assertIn("bash scripts/bootstrap.sh", result.stderr)

    def test_start_fails_when_requirements_stamp_is_outdated(self) -> None:
        venv_bin = self.repo_root / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        python_bin = venv_bin / "python"
        python_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        python_bin.chmod(0o755)

        stamp_file = self.repo_root / ".venv" / ".infra-ai-requirements.sha256"
        stamp_file.write_text("stale-hash\n", encoding="utf-8")

        result = self.run_start()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requirements.txt changed since the last bootstrap", result.stderr)
        self.assertIn("bash scripts/bootstrap.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
