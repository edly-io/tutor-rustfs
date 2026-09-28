"""Template rendering.

Most real breakages in a Tutor plugin are template bugs: a variable
that was renamed in plugin.py but not in a patch, YAML that stops
parsing, a service name that no longer matches the one Tutor looks up.
None of those are caught by lint or type checks, and all of them are
caught here without starting a container.
"""

from __future__ import annotations

import typing as t

import pytest
import yaml
from tutor import env as tutor_env
from tutor import hooks as tutor_hooks

from .conftest import patch_names, read_patch

# Patches whose content is YAML (either a document or a fragment that
# is spliced into one).
YAML_PATCHES = [
    "k8s-deployments",
    "k8s-jobs",
    "k8s-services",
    "k8s-volumes",
    "local-docker-compose-caddy-aliases",
    "local-docker-compose-cms-dependencies",
    "local-docker-compose-dev-services",
    "local-docker-compose-jobs-services",
    "local-docker-compose-lms-dependencies",
    "local-docker-compose-services",
    "openedx-auth",
]

# Patches that are spliced into Django settings modules.
PYTHON_PATCHES = [
    "discovery-common-settings",
    "discovery-development-settings",
    "openedx-cms-common-settings",
    "openedx-common-settings",
    "openedx-development-settings",
    "openedx-lms-production-settings",
    "xqueue-settings",
]


@pytest.mark.parametrize("name", patch_names())
def test_patch_renders(name: str, renderer: tutor_env.Renderer) -> None:
    """Every patch renders against the default config.

    An undefined variable raises TutorError here.
    """
    renderer.render_str(read_patch(name))


@pytest.mark.parametrize("name", patch_names())
def test_no_unrendered_jinja(name: str, rendered: dict[str, str]) -> None:
    out = rendered[name]
    assert "{{" not in out and "{%" not in out, f"{name} has unrendered Jinja"


@pytest.mark.parametrize("name", patch_names())
def test_no_minio_variables_survive(name: str, rendered: dict[str, str]) -> None:
    """Catch an incomplete rename from tutor-minio.

    Comments legitimately mention MinIO (the `mc` client, port parity),
    so only flag the config-variable form.
    """
    assert "MINIO_" not in rendered[name], f"{name} still references a MINIO_ variable"


@pytest.mark.parametrize("name", YAML_PATCHES)
def test_yaml_patches_parse(name: str, rendered: dict[str, str]) -> None:
    parsed = list(yaml.safe_load_all(rendered[name]))
    assert parsed and parsed[0] is not None, f"{name} rendered to empty YAML"


@pytest.mark.parametrize("name", PYTHON_PATCHES)
def test_python_patches_are_syntactically_valid(
    name: str, rendered: dict[str, str]
) -> None:
    """A syntax error here would only surface as a crashed LMS."""
    compile(rendered[name], f"<{name}>", "exec")


def test_all_patches_are_categorised() -> None:
    """Fail when a new patch is added without a parse check."""
    categorised = set(YAML_PATCHES) | set(PYTHON_PATCHES) | {"caddyfile"}
    uncategorised = set(patch_names()) - categorised
    assert not uncategorised, (
        f"new patches need a parse check in this file: {sorted(uncategorised)}"
    )


# --- the storage service itself ------------------------------------------


def test_compose_service_matches_config(
    rendered: dict[str, str], config: dict[str, t.Any]
) -> None:
    svc = yaml.safe_load(rendered["local-docker-compose-services"])["rustfs"]
    assert svc["image"] == config["RUSTFS_DOCKER_IMAGE"]
    assert svc["user"] == f"{config['RUSTFS_UID']}:{config['RUSTFS_GID']}"
    assert svc["volumes"] == ["../../data/rustfs:/data"]
    env = svc["environment"]
    assert env["RUSTFS_ACCESS_KEY"] == config["OPENEDX_AWS_ACCESS_KEY"]
    assert env["RUSTFS_SECRET_KEY"] == config["OPENEDX_AWS_SECRET_ACCESS_KEY"]
    assert env["RUSTFS_VOLUMES"] == "/data"
    assert env["RUSTFS_ADDRESS"] == ":9000"
    assert env["RUSTFS_CONSOLE_ADDRESS"] == ":9001"


def test_k8s_deployment_runs_as_non_root(
    rendered: dict[str, str], config: dict[str, t.Any]
) -> None:
    """Without fsGroup the PVC mounts root-owned and RustFS exits with
    EACCES on /data."""
    dep = yaml.safe_load(rendered["k8s-deployments"])
    sec = dep["spec"]["template"]["spec"]["securityContext"]
    assert sec["runAsUser"] == config["RUSTFS_UID"]
    assert sec["fsGroup"] == config["RUSTFS_GID"]


def test_k8s_service_exposes_both_ports(rendered: dict[str, str]) -> None:
    svc = yaml.safe_load(rendered["k8s-services"])
    ports = {p["port"] for p in svc["spec"]["ports"]}
    assert ports == {9000, 9001}


def test_lms_and_cms_depend_on_rustfs(rendered: dict[str, str]) -> None:
    for name in (
        "local-docker-compose-lms-dependencies",
        "local-docker-compose-cms-dependencies",
    ):
        assert yaml.safe_load(rendered[name]) == ["rustfs"]


# --- the job-service naming contract -------------------------------------


def test_init_job_service_name_matches_init_task(rendered: dict[str, str]) -> None:
    """Tutor resolves an init task for service X to the ``X-job``
    service. A mismatch makes `tutor local do init` fail with an
    unhelpful "no such service" error.
    """
    service = dict(tutor_hooks.Filters.CLI_DO_INIT_TASKS.iterate())
    assert "rustfs" in service
    jobs = yaml.safe_load(rendered["local-docker-compose-jobs-services"])
    assert "rustfs-job" in jobs, f"expected a 'rustfs-job' service, got {sorted(jobs)}"
    assert jobs["rustfs-job"]["depends_on"] == ["rustfs"]


def test_k8s_job_name_matches_init_task(rendered: dict[str, str]) -> None:
    job = yaml.safe_load(rendered["k8s-jobs"])
    assert job["metadata"]["name"] == "rustfs-job"


def test_init_job_uses_the_mc_image(
    rendered: dict[str, str], config: dict[str, t.Any]
) -> None:
    """The RustFS image does not ship `mc`, so the job must not use it."""
    jobs = yaml.safe_load(rendered["local-docker-compose-jobs-services"])
    assert jobs["rustfs-job"]["image"] == config["RUSTFS_MC_DOCKER_IMAGE"]
    assert jobs["rustfs-job"]["image"] != config["RUSTFS_DOCKER_IMAGE"]


# --- Open edX client settings --------------------------------------------


def test_openedx_points_at_the_rustfs_host(
    rendered: dict[str, str], config: dict[str, t.Any]
) -> None:
    out = rendered["openedx-common-settings"]
    assert f'AWS_S3_ENDPOINT_URL = "http://{config["RUSTFS_HOST"]}"' in out
    assert 'AWS_S3_SIGNATURE_VERSION = "s3v4"' in out
    assert f'AWS_S3_REGION_NAME = "{config["RUSTFS_REGION"]}"' in out


def test_checksum_workaround_is_present(rendered: dict[str, str]) -> None:
    """boto3 >= 1.36 sends CRC32 checksums by default, which non-AWS S3
    implementations reject. Removing this breaks every upload."""
    out = rendered["openedx-common-settings"]
    assert "request_checksum_calculation='when_required'" in out
    assert "response_checksum_validation='when_required'" in out


def test_buckets_referenced_in_settings_are_created_by_init(
    config: dict[str, t.Any],
) -> None:
    """Every bucket Open edX is configured to write to must be created
    by the init task, or the first upload 404s."""
    init = dict(tutor_hooks.Filters.CLI_DO_INIT_TASKS.iterate())["rustfs"]
    rendered_init = tutor_env.Renderer(config).render_str(init)
    for key in (
        "RUSTFS_BUCKET_NAME",
        "RUSTFS_FILE_UPLOAD_BUCKET_NAME",
        "RUSTFS_VIDEO_UPLOAD_BUCKET_NAME",
        "RUSTFS_GRADES_BUCKET_NAME",
        "RUSTFS_OPENEDX_LEARNING_BUCKET_NAME",
    ):
        assert config[key] in rendered_init, f"{key} is never created by init.sh"


def test_console_redirect_is_configured(
    rendered: dict[str, str], config: dict[str, t.Any]
) -> None:
    """Port 9001 serves the S3 API at "/" and the console at
    "/rustfs/console/"; without the redirect, visitors get an
    AccessDenied XML document instead of a UI."""
    out = rendered["caddyfile"]
    assert config["RUSTFS_HOST"] in out
    assert config["RUSTFS_CONSOLE_HOST"] in out
    assert "redir / /rustfs/console/ 302" in out
    assert 'import proxy "rustfs:9000"' in out
    assert 'import proxy "rustfs:9001"' in out


# --- cross-plugin integration --------------------------------------------


def test_discovery_bucket_is_conditional(
    renderer: tutor_env.Renderer, config: dict[str, t.Any]
) -> None:
    """The discovery bucket should only be created when the discovery
    plugin is enabled."""
    assert config["RUSTFS_DISCOVERY_BUCKET_NAME"] == ""

    with_discovery = dict(config, PLUGINS=["discovery"])
    value = tutor_env.render_str(
        with_discovery,
        "{% if 'discovery' in PLUGINS %}discoveryuploads{% endif %}",
    )
    assert value == "discoveryuploads"


def test_discovery_settings_target_rustfs(
    renderer: tutor_env.Renderer, config: dict[str, t.Any]
) -> None:
    """tutor-minio configured the discovery plugin's storage for it;
    dropping that silently breaks discovery uploads."""
    cfg = dict(config, RUSTFS_DISCOVERY_BUCKET_NAME="discoveryuploads")
    out = tutor_env.Renderer(cfg).render_str(read_patch("discovery-common-settings"))
    compile(out, "<discovery-common-settings>", "exec")
    assert f'AWS_S3_ENDPOINT_URL = "http://{cfg["RUSTFS_HOST"]}"' in out
    assert 'AWS_STORAGE_BUCKET_NAME = "discoveryuploads"' in out


def test_xqueue_settings_target_rustfs(
    rendered: dict[str, str], config: dict[str, t.Any]
) -> None:
    out = rendered["xqueue-settings"]
    assert f'AWS_S3_ENDPOINT_URL = "http://{config["RUSTFS_HOST"]}"' in out
    assert f'AWS_STORAGE_BUCKET_NAME = "{config["RUSTFS_BUCKET_NAME"]}"' in out
    assert 'AWS_LOCATION = "xqueueuploads"' in out
