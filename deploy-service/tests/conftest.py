"""Shared fixtures for deploy_service's test suite."""
import pytest

from deploy_service.target import Target


@pytest.fixture
def local_target() -> Target:
    return Target.local()


@pytest.fixture
def remote_target() -> Target:
    return Target(is_local=False, host="10.0.0.5", port=2222, user="homelab", key_file=None)


@pytest.fixture
def write_yaml(tmp_path):
    """Returns a function that writes `content` to `tmp_path/name` (creating
    parent dirs as needed) and returns its Path."""
    def _write(name: str, content: str):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path
    return _write
