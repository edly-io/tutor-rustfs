"""Configuration and hook registration."""

from __future__ import annotations

import typing as t

import pytest
from tutor import exceptions as tutor_exceptions
from tutor import hooks as tutor_hooks

from tutorrustfs.plugin import check_plugin_conflict

# Keys this plugin is expected to define. Kept explicit rather than
# derived from plugin.py so that accidentally dropping one fails.
EXPECTED_KEYS = {
    "RUSTFS_VERSION",
    "RUSTFS_BUCKET_NAME",
    "RUSTFS_FILE_UPLOAD_BUCKET_NAME",
    "RUSTFS_VIDEO_UPLOAD_BUCKET_NAME",
    "RUSTFS_GRADES_BUCKET_NAME",
    "RUSTFS_OPENEDX_LEARNING_BUCKET_NAME",
    "RUSTFS_DISCOVERY_BUCKET_NAME",
    "RUSTFS_HOST",
    "RUSTFS_CONSOLE_HOST",
    "RUSTFS_REGION",
    "RUSTFS_QUERYSTRING_AUTH",
    "RUSTFS_DOCKER_IMAGE",
    "RUSTFS_MC_DOCKER_IMAGE",
    "RUSTFS_UID",
    "RUSTFS_GID",
    "RUSTFS_AWS_SECRET_ACCESS_KEY",
}


def test_all_expected_keys_are_defined(config: dict[str, t.Any]) -> None:
    missing = EXPECTED_KEYS - set(config)
    assert not missing, f"missing config keys: {sorted(missing)}"


def test_no_minio_keys_leak(config: dict[str, t.Any]) -> None:
    """A MINIO_* key would mean an incomplete rename from tutor-minio."""
    leaked = sorted(k for k in config if k.startswith("MINIO_"))
    assert not leaked, f"MINIO_-prefixed config keys survived the fork: {leaked}"


def test_plugin_config_is_namespaced(config: dict[str, t.Any]) -> None:
    """Every key this plugin adds must be RUSTFS_-prefixed.

    tutor-minio shipped an unprefixed ``MC_DOCKER_IMAGE`` which polluted
    the global Tutor namespace. Guard against repeating that.
    """
    unprefixed = {"MC_DOCKER_IMAGE", "DOCKER_IMAGE", "BUCKET_NAME", "REGION", "UID"}
    collisions = sorted(unprefixed & set(config))
    assert not collisions, f"unprefixed keys pollute the global namespace: {collisions}"


def test_no_gateway_setting(config: dict[str, t.Any]) -> None:
    """RustFS has no gateway mode; a setting implying otherwise misleads."""
    assert "RUSTFS_GATEWAY" not in config


def test_openedx_credentials_are_wired(config: dict[str, t.Any]) -> None:
    assert config["OPENEDX_AWS_ACCESS_KEY"] == "openedx"
    secret = config["OPENEDX_AWS_SECRET_ACCESS_KEY"]
    assert secret == config["RUSTFS_AWS_SECRET_ACCESS_KEY"]
    assert len(str(secret)) == 24, "secret should be a generated 24-char string"
    assert "{{" not in str(secret), "secret was not rendered"


def test_hosts_derive_from_lms_host(config: dict[str, t.Any]) -> None:
    lms = config["LMS_HOST"]
    assert config["RUSTFS_HOST"] == f"files.{lms}"
    assert config["RUSTFS_CONSOLE_HOST"] == f"rustfs.{lms}"


def test_region_matches_rustfs_default(config: dict[str, t.Any]) -> None:
    """RustFS's own built-in default is us-east-1; diverging silently
    would make presigned URLs fail signature validation."""
    assert config["RUSTFS_REGION"] == "us-east-1"


def test_docker_image_is_pinned(config: dict[str, t.Any]) -> None:
    image = config["RUSTFS_DOCKER_IMAGE"]
    assert image.startswith("docker.io/rustfs/rustfs:")
    tag = image.split(":", 1)[1]
    assert tag != "latest", "pin an explicit tag so deployments are reproducible"


def test_init_task_registered_for_rustfs_service() -> None:
    tasks = dict(tutor_hooks.Filters.CLI_DO_INIT_TASKS.iterate())
    assert "rustfs" in tasks, f"no init task for 'rustfs'; got {sorted(tasks)}"
    script = tasks["rustfs"]
    assert "mc mb" in script
    assert "mc policy set download" in script


def test_public_buckets_are_read_only() -> None:
    """`mc policy set public` means anonymous read *and write*.

    Using it lets anyone who can reach RUSTFS_HOST upload to and delete
    from the bucket without credentials. `download` is read-only, which
    is all forum images and public assets need.
    """
    script = dict(tutor_hooks.Filters.CLI_DO_INIT_TASKS.iterate())["rustfs"]
    assert "mc policy set public" not in script, (
        "`mc policy set public` grants anonymous write; use `download`"
    )
    assert "mc policy set upload" not in script
    assert "mc anonymous set public" not in script


def test_console_host_is_publicly_routed() -> None:
    hosts = tutor_hooks.Filters.APP_PUBLIC_HOSTS.apply([], "local")
    assert "{{ RUSTFS_CONSOLE_HOST }}" in hosts
    dev_hosts = tutor_hooks.Filters.APP_PUBLIC_HOSTS.apply([], "dev")
    assert "{{ RUSTFS_CONSOLE_HOST }}:9001" in dev_hosts


def test_refuses_to_run_alongside_tutor_minio() -> None:
    with pytest.raises(tutor_exceptions.TutorError, match="cannot be enabled"):
        check_plugin_conflict("minio")


def test_other_plugins_do_not_trigger_conflict() -> None:
    check_plugin_conflict("discovery")
    check_plugin_conflict("mfe")
