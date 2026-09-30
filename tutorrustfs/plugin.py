from __future__ import annotations

import os
import typing as t
from glob import glob

import importlib_resources
from tutor import exceptions as tutor_exceptions
from tutor import hooks as tutor_hooks
from tutor.__about__ import __version_suffix__

from .__about__ import __version__

# Handle version suffix in main mode, just like tutor core
if __version_suffix__:
    __version__ += "-" + __version_suffix__

HERE = os.path.abspath(os.path.dirname(__file__))

# -----------------------------------------------------------------------------
# RustFS object storage for Open edX.
#
# This plugin is a successor to tutor-minio. MinIO was archived upstream
# (last release RELEASE.2025-10-15T17-29-55Z), so this plugin runs
# RustFS (https://github.com/rustfs/rustfs) instead: a Rust
# reimplementation of the MinIO S3 API that uses the same ports and the
# same bucket policy semantics. Bucket provisioning uses `rc`
# (https://github.com/rustfs/cli), RustFS's own S3-compatible CLI,
# rather than MinIO's `mc`: MinIO Inc. pulled `mc` from Docker Hub and
# then, in September 2026, locked down anonymous pulls from Quay too,
# so depending on it here would mean inheriting that registry risk for
# no reason — RustFS's own tooling is already a required trust
# boundary for this plugin.
#
# Feature parity with tutor-minio is intentional, with one exception:
# there is no gateway mode. MinIO removed gateway mode in 2022 and
# RustFS never had it. To use an external S3 provider (AWS, GCS, Ceph,
# or any S3-compatible vendor), use tutor-contrib-s3 instead of this
# plugin:
#
#     https://github.com/cleura/tutor-contrib-s3
#
# This plugin and tutor-minio cannot be enabled at the same time: they
# both set STORAGES["default"], both claim ports 9000/9001, and both
# claim reverse-proxy vhosts. See the check_plugin_conflict action
# below.
# -----------------------------------------------------------------------------

config: dict[str, dict[str, t.Any]] = {
    "defaults": {
        "VERSION": __version__,
        # Buckets. The default names match tutor-minio's so that objects
        # exported from a MinIO deployment can be re-imported without
        # renaming anything.
        "BUCKET_NAME": "openedx",
        "FILE_UPLOAD_BUCKET_NAME": "openedxuploads",
        "VIDEO_UPLOAD_BUCKET_NAME": "openedxvideos",
        "GRADES_BUCKET_NAME": "openedxgrades",
        "OPENEDX_LEARNING_BUCKET_NAME": "openedxlearning",
        "DISCOVERY_BUCKET_NAME": "{% if 'discovery' in PLUGINS %}discoveryuploads{% endif %}",  # noqa: E501
        # Hostnames. RUSTFS_HOST serves the S3 API and must be reachable
        # from learners' browsers, not just from the Open edX
        # containers: presigned download URLs and public asset URLs are
        # generated against it.
        "HOST": "files.{{ LMS_HOST }}",
        "CONSOLE_HOST": "rustfs.{{ LMS_HOST }}",
        # Matches RustFS's own built-in default; changing it here also
        # changes the value passed to the server.
        "REGION": "us-east-1",
        "QUERYSTRING_AUTH": True,
        # https://hub.docker.com/r/rustfs/rustfs/tags
        # Pinned to an explicit tag rather than `latest` so that a
        # `tutor local launch` is reproducible and an upstream push
        # can't silently change the object store under a running
        # deployment. Multi-arch (linux/amd64 + linux/arm64).
        "DOCKER_IMAGE": "docker.io/rustfs/rustfs:1.0.0",
        # The RustFS image does not ship a client, so the init/admin job
        # runs from `rc`'s own image, published by the RustFS project at
        # https://hub.docker.com/r/rustfs/rc. Pinned to an explicit tag
        # for the same reason as RUSTFS_DOCKER_IMAGE above.
        "RC_DOCKER_IMAGE": "docker.io/rustfs/rc:v0.1.36",
        # RustFS containers run as UID 10001. We pass this explicitly to
        # the `user:` directive so one-shot commands don't run as root
        # and leave root-owned files in the data volume. Override if
        # your host's user namespace maps the container user
        # differently (e.g. rootless Docker).
        "UID": 10001,
        "GID": 10001,
    },
    "unique": {
        "AWS_SECRET_ACCESS_KEY": "{{ 24|random_string }}",
    },
    "overrides": {
        "OPENEDX_AWS_ACCESS_KEY": "openedx",
        "OPENEDX_AWS_SECRET_ACCESS_KEY": "{{ RUSTFS_AWS_SECRET_ACCESS_KEY }}",
    },
}

tutor_hooks.Filters.CONFIG_DEFAULTS.add_items(
    [(f"RUSTFS_{key}", value) for key, value in config.get("defaults", {}).items()]
)
tutor_hooks.Filters.CONFIG_UNIQUE.add_items(
    [(f"RUSTFS_{key}", value) for key, value in config.get("unique", {}).items()]
)
tutor_hooks.Filters.CONFIG_OVERRIDES.add_items(
    list(config.get("overrides", {}).items())
)


@tutor_hooks.Actions.PLUGIN_LOADED.add()
def check_plugin_conflict(plugin_name: str) -> None:
    """Refuse to run alongside tutor-minio.

    Both plugins set STORAGES["default"], bind ports 9000/9001 and claim
    reverse-proxy vhosts. Enabling both produces a stack that starts and
    then misbehaves in ways that are hard to trace back here, so fail
    loudly instead.
    """
    if plugin_name == "minio":
        raise tutor_exceptions.TutorError(
            "The 'minio' and 'rustfs' plugins cannot be enabled at the same "
            "time: they both configure Open edX object storage and bind the "
            "same ports. Disable one of them:\n"
            "    tutor plugins disable minio"
        )


@tutor_hooks.Filters.APP_PUBLIC_HOSTS.add()
def add_rustfs_hosts(
    hosts: list[str], context_name: t.Literal["local", "dev"]
) -> list[str]:
    # Same default port map as MinIO: S3 API on 9000, console on 9001.
    if context_name == "dev":
        hosts.append("{{ RUSTFS_CONSOLE_HOST }}:9001")
    else:
        hosts.append("{{ RUSTFS_CONSOLE_HOST }}")
    return hosts


# Bucket provisioning. The service name registered here must have a
# matching `<name>-job` service in the local and k8s job patches.
with open(
    os.path.join(HERE, "templates", "rustfs", "tasks", "rustfs", "init.sh"),
    encoding="utf-8",
) as fi:
    tutor_hooks.Filters.CLI_DO_INIT_TASKS.add_item(
        ("rustfs", fi.read()), priority=tutor_hooks.priorities.HIGH
    )

# Add the "templates" folder as a template root
tutor_hooks.Filters.ENV_TEMPLATE_ROOTS.add_item(
    str(importlib_resources.files("tutorrustfs") / "templates")
)
# Render the "build" and "apps" folders
tutor_hooks.Filters.ENV_TEMPLATE_TARGETS.add_items(
    [
        ("rustfs/build", "plugins"),
        ("rustfs/apps", "plugins"),
    ],
)
# Load patches from files
for path in glob(str(importlib_resources.files("tutorrustfs") / "patches" / "*")):
    with open(path, encoding="utf-8") as patch_file:
        tutor_hooks.Filters.ENV_PATCHES.add_item(
            (os.path.basename(path), patch_file.read())
        )
