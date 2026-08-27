"""Tests for deploy_service.compose — local/remote branching for file reads,
git clone/pull, hook execution, and docker compose deploy."""
from types import SimpleNamespace

import pytest

from deploy_service import compose


class _RecordingRun:
    """Stand-in for subprocess.run that records every invocation regardless
    of which kwargs a given call site passes (cwd/env/input/capture_output
    all vary across compose.py's call sites)."""
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls: list[dict] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


class TestMask:
    def test_masks_secret_in_display(self):
        display = compose._mask(["git", "clone", "https://x-access-token:supersecret@github.com/x/y"], "supersecret")
        assert "supersecret" not in display
        assert "***" in display

    def test_no_secret_leaves_display_unchanged(self):
        display = compose._mask(["git", "status"], None)
        assert display == "git status"


class TestReadFile:
    def test_local_existing_file(self, tmp_path, local_target):
        f = tmp_path / "secrets.yml"
        f.write_text("secrets: []\n")
        assert compose.read_file(str(f), target=local_target) == "secrets: []\n"

    def test_local_missing_file_returns_none(self, tmp_path, local_target):
        missing = tmp_path / "secrets.yml"
        assert compose.read_file(str(missing), target=local_target) is None

    def test_remote_dry_run_never_connects(self, monkeypatch, remote_target):
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)
        result = compose.read_file("/srv/services/authentik-sso/secrets.yml", target=remote_target, dry_run=True)
        assert result is None
        assert run.calls == []

    def test_remote_success(self, monkeypatch, remote_target):
        # read_file's remote branch uses subprocess.run(..., capture_output=True)
        # with no text=True, so stdout comes back as bytes, decoded by read_file itself.
        run = _RecordingRun(returncode=0, stdout=b"secrets:\n  - path: /prod/x/Y\n")
        monkeypatch.setattr(compose.subprocess, "run", run)
        result = compose.read_file("/srv/services/x/secrets.yml", target=remote_target)
        assert result == "secrets:\n  - path: /prod/x/Y\n"

    def test_remote_missing_returns_none(self, monkeypatch, remote_target):
        run = _RecordingRun(returncode=1, stdout="")
        monkeypatch.setattr(compose.subprocess, "run", run)
        result = compose.read_file("/srv/services/x/secrets.yml", target=remote_target)
        assert result is None


class TestCloneOrPull:
    def test_local_clone_when_absent(self, monkeypatch, tmp_path, local_target):
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)
        dest = tmp_path / "authentik-sso"

        compose.clone_or_pull("github.com/x/authentik-sso", str(dest), ref="main", target=local_target)

        assert dest.exists()  # mkdir happened
        cmds = [c["cmd"] for c in run.calls]
        assert ["git", "clone", "https://github.com/x/authentik-sso.git", str(dest)] in cmds
        assert ["git", "-C", str(dest), "checkout", "main"] in cmds

    def test_local_pull_when_present(self, monkeypatch, tmp_path, local_target):
        dest = tmp_path / "authentik-sso"
        (dest / ".git").mkdir(parents=True)
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)

        compose.clone_or_pull("github.com/x/authentik-sso", str(dest), ref="main", target=local_target)

        cmds = [c["cmd"] for c in run.calls]
        assert ["git", "-C", str(dest), "reset", "--hard"] in cmds
        assert ["git", "-C", str(dest), "pull", "--ff-only"] in cmds
        assert not any(c[:2] == ["git", "clone"] for c in cmds)

    def test_github_token_never_left_in_remote_url(self, monkeypatch, tmp_path, local_target):
        dest = tmp_path / "authentik-sso"
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)

        compose.clone_or_pull(
            "github.com/x/authentik-sso", str(dest), ref="main",
            target=local_target, github_token="ghp_secret123",
        )

        cmds = [c["cmd"] for c in run.calls]
        set_url_cmds = [c for c in cmds if c[:4] == ["git", "-C", str(dest), "remote"]]
        # Rewritten to the authenticated URL for the clone, then rewritten
        # straight back to the bare (token-free) URL -- never left at rest.
        assert ["git", "clone", "https://x-access-token:ghp_secret123@github.com/x/authentik-sso.git", str(dest)] in cmds
        assert set_url_cmds[-1] == ["git", "-C", str(dest), "remote", "set-url", "origin", "https://github.com/x/authentik-sso.git"]

    def test_remote_dry_run_never_connects(self, monkeypatch, remote_target):
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)

        compose.clone_or_pull(
            "github.com/x/homelab-observe-services", "/srv/services/homelab-observe-services",
            ref="master", target=remote_target, dry_run=True,
        )

        assert run.calls == []

    def test_remote_clone_when_absent(self, monkeypatch, remote_target):
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)
        # Bypass the `test -d` existence probe directly -- report "absent" so
        # the clone (not pull) branch runs; everything after it uses `run`.
        monkeypatch.setattr(compose, "_remote_path_exists", lambda target, path, test_flag="-d": False)

        compose.clone_or_pull(
            "github.com/x/homelab-observe-services", "/srv/services/homelab-observe-services",
            ref="master", target=remote_target,
        )

        scripts = [c.get("input", b"").decode() for c in run.calls if "input" in c]
        assert any("mkdir -p" in s for s in scripts)
        assert any("git clone" in s for s in scripts)


class TestRunConventionalHook:
    def test_local_hook_present_runs_it(self, monkeypatch, tmp_path, local_target):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "postdeploy.sh").write_text("#!/bin/sh\n")
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)

        compose.run_conventional_hook(str(tmp_path), "postdeploy.sh", {}, "post-deploy", target=local_target)

        assert [c["cmd"] for c in run.calls] == [["bash", "scripts/postdeploy.sh"]]

    def test_local_hook_absent_skips_silently(self, monkeypatch, tmp_path, local_target, capsys):
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)

        compose.run_conventional_hook(str(tmp_path), "postdeploy.sh", {}, "post-deploy", target=local_target)

        assert run.calls == []
        assert "No post-deploy hook" in capsys.readouterr().out

    def test_remote_dry_run_never_connects(self, monkeypatch, remote_target):
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)

        compose.run_conventional_hook(
            "/srv/services/x", "predeploy.sh", {}, "pre-deploy", target=remote_target, dry_run=True,
        )

        assert run.calls == []


class TestCheckRolling:
    def test_rolling_is_accepted(self):
        compose._check_rolling("rolling")  # must not raise

    def test_other_strategy_exits(self):
        with pytest.raises(SystemExit) as exc:
            compose._check_rolling("recreate")
        assert "rolling" in str(exc.value)


class TestDeployCommands:
    def test_deploy_pulls_then_ups(self, monkeypatch, local_target):
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)

        compose.deploy("/srv/services/x", ["docker-compose.yml"], {"FOO": "bar"}, target=local_target)

        cmds = [c["cmd"] for c in run.calls]
        assert ["docker", "compose", "-f", "docker-compose.yml", "pull", "-q"] in cmds
        assert ["docker", "compose", "-f", "docker-compose.yml", "up", "-d", "--remove-orphans"] in cmds
        # never a bare `down` -- see the rolling-only constraint in the module docstring
        assert not any("down" in c for c in cmds)

    def test_deploy_rejects_non_rolling_strategy(self, local_target):
        with pytest.raises(SystemExit):
            compose.deploy("/srv/services/x", ["docker-compose.yml"], {}, strategy="recreate", target=local_target)

    def test_pull_image_pulls_explicit_tag(self, monkeypatch, local_target):
        run = _RecordingRun()
        monkeypatch.setattr(compose.subprocess, "run", run)

        compose.pull_image("ghcr.io/x/bottlebot", "v1.2.3", target=local_target)

        assert [c["cmd"] for c in run.calls] == [["docker", "pull", "-q", "ghcr.io/x/bottlebot:v1.2.3"]]
