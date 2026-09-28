Object storage for Open edX with `RustFS <https://github.com/rustfs/rustfs>`_
=============================================================================

This is a plugin for `Tutor <https://docs.tutor.edly.io>`_ that provides
S3-compatible object storage for Open edX platforms, backed by
`RustFS <https://github.com/rustfs/rustfs>`_ — a Rust reimplementation of the
MinIO S3 API. It is the successor to ``tutor-minio``, which is no longer
viable now that `MinIO is archived
<https://github.com/minio/minio>`_.

Object storage is required for `Kubernetes deployment
<https://docs.tutor.edly.io/k8s.html>`_, and for any installation running more
than one application server, because Open edX's default local-filesystem
storage cannot be shared between them.

.. warning::

   RustFS published its first stable release (1.0.0) recently. It has a short
   production track record. Evaluate it against your own workload before
   putting course data on it, and see `Migrating from tutor-minio`_ for the
   export/import procedure.

Which plugin do I want?
-----------------------

There are two different jobs here, and they need different plugins.

.. list-table::
   :header-rows: 1

   * - You want
     - Use
   * - An S3 server on your own hardware, alongside Open edX
     - **this plugin**
   * - AWS S3, GCS, Ceph, or any external S3-compatible provider
     - `tutor-contrib-s3 <https://github.com/cleura/tutor-contrib-s3>`_
   * - RustFS or MinIO running on a *separate* machine
     - `tutor-contrib-s3 <https://github.com/cleura/tutor-contrib-s3>`_, pointed at it
   * - Azure Blob Storage
     - Nothing available today — see `No gateway mode`_

This plugin runs the storage server *and* configures Open edX to use it, which
means both live on the same host. ``tutor-contrib-s3`` only configures Open
edX, so it is the right choice whenever the server is somewhere else.

Installation
------------

::

    pip install tutor-rustfs
    tutor plugins enable rustfs

.. note::

   This plugin and ``tutor-minio`` cannot be enabled at the same time. Both set
   ``STORAGES["default"]``, bind ports 9000/9001, and claim reverse-proxy
   vhosts. Enabling both raises an error.

No gateway mode
---------------

MinIO once had a ``gateway`` mode that let it proxy to an external backend,
including Azure Blob Storage, which has no S3 API of its own. MinIO deprecated
gateway mode in 2022 and removed it shortly afterwards; ``tutor-minio`` kept it
working only by pinning ``mc`` to a 2022 image. **RustFS has no equivalent, and
this plugin does not provide one.** There is no ``RUSTFS_GATEWAY`` setting.

- For **AWS, GCS, Ceph, or any S3-compatible provider**, use
  ``tutor-contrib-s3``. It talks to the provider directly, which is both
  simpler and faster than proxying.
- For **Azure Blob Storage**, there is currently no maintained option. If this
  affects you, please say so on the `Open edX forum
  <https://discuss.openedx.org/t/rustfs-plugin-to-replace-tutor-minio-thoughts-on-azure-gateway/19670>`_.

Configuration
-------------

Shared with Open edX (these drive the S3 client settings):

- ``OPENEDX_AWS_ACCESS_KEY`` (default: ``"openedx"``)
- ``OPENEDX_AWS_SECRET_ACCESS_KEY`` (default: randomly generated)

Buckets — the default names match ``tutor-minio``'s, so objects exported from a
MinIO deployment can be re-imported without renaming:

- ``RUSTFS_BUCKET_NAME`` (default: ``"openedx"``)
- ``RUSTFS_FILE_UPLOAD_BUCKET_NAME`` (default: ``"openedxuploads"``)
- ``RUSTFS_VIDEO_UPLOAD_BUCKET_NAME`` (default: ``"openedxvideos"``)
- ``RUSTFS_GRADES_BUCKET_NAME`` (default: ``"openedxgrades"``)
- ``RUSTFS_OPENEDX_LEARNING_BUCKET_NAME`` (default: ``"openedxlearning"``)
- ``RUSTFS_DISCOVERY_BUCKET_NAME`` (default: ``"discoveryuploads"`` when the
  ``discovery`` plugin is enabled, otherwise empty)

Hosts:

- ``RUSTFS_HOST`` (default: ``"files.{{ LMS_HOST }}"``) — the S3 API endpoint.
  **This must resolve from learners' browsers**, not only from the Open edX
  containers: presigned download URLs and public asset URLs are generated
  against it.
- ``RUSTFS_CONSOLE_HOST`` (default: ``"rustfs.{{ LMS_HOST }}"``) — the web
  console.

Server:

- ``RUSTFS_DOCKER_IMAGE`` (default: ``"docker.io/rustfs/rustfs:1.0.0"``) —
  pinned to an explicit tag so deployments are reproducible. Multi-arch
  (``linux/amd64`` and ``linux/arm64``).
- ``RUSTFS_MC_DOCKER_IMAGE`` — the MinIO Client image used by the bucket
  provisioning job. The RustFS image does not ship ``mc``, and RustFS is
  wire-compatible with it.
- ``RUSTFS_REGION`` (default: ``"us-east-1"``) — matches RustFS's own default.
- ``RUSTFS_UID`` / ``RUSTFS_GID`` (both default: ``10001``) — the non-root user
  inside the container.
- ``RUSTFS_QUERYSTRING_AUTH`` (default: ``true``)

Non-root caveat
---------------

RustFS runs as non-root UID ``10001``. On a **fresh install on a Linux host**
this is a required extra step, not just a troubleshooting note: when the
bind-mount source does not exist yet, the Docker daemon creates it owned by
``root:root`` and RustFS aborts on startup with::

    [FATAL] Server runtime failed: Io error: Permission denied (os error 13)

Create the directory with the right owner *before* your first
``tutor local start``::

    mkdir -p "$(tutor config printroot)/data/rustfs"
    sudo chown -R 10001:10001 "$(tutor config printroot)/data/rustfs"

Docker Desktop on macOS and Windows maps bind-mount ownership to the host user,
so this only affects native Linux — i.e. most production hosts.

In Kubernetes the ``fsGroup: 10001`` on the Deployment handles this
automatically.

DNS records
-----------

Both ``RUSTFS_HOST`` and ``RUSTFS_CONSOLE_HOST`` must point at your server.

Web UI
------

RustFS does **not** serve its console at the root of the console port: port
``9001`` serves the S3 API at ``/`` and mounts the console under
``/rustfs/console/``. Hitting ``/`` directly returns an S3 ``AccessDenied`` XML
document rather than a UI. The ``caddyfile`` patch issues a
``redir / /rustfs/console/``, so in local and production mode the console is
reachable at ``http://<RUSTFS_CONSOLE_HOST>`` as usual. In development mode,
where there is no Caddy in front, use the full path::

    http://rustfs.local.openedx.io:9001/rustfs/console/

Log in with::

    tutor config printvalue OPENEDX_AWS_ACCESS_KEY
    tutor config printvalue OPENEDX_AWS_SECRET_ACCESS_KEY

Migrating from tutor-minio
--------------------------

**There is no in-place migration.** RustFS cannot read a MinIO data directory
in the stock image: upstream ships MinIO on-disk compatibility behind the
``rio-v2`` cargo feature, which is not part of the default build, and objects
MinIO wrote encrypted are not readable by RustFS at all. Pointing RustFS at
your existing ``data/minio`` volume will not migrate anything.

1. **Export your objects with** ``mc mirror`` **while MinIO is still running.**
   This step is not optional::

       mc mirror minio/openedx ./backup/openedx/

   Repeat for each bucket.

2. Disable the old plugin and enable this one::

       tutor plugins disable minio
       tutor plugins enable rustfs

3. Port your configuration. Every ``MINIO_*`` key has a ``RUSTFS_*``
   equivalent with the same default value, with two exceptions:

   - ``MINIO_GATEWAY`` has no equivalent. See `No gateway mode`_.
   - ``MINIO_CONSOLE_HOST`` defaulted to ``minio.{{ LMS_HOST }}``;
     ``RUSTFS_CONSOLE_HOST`` defaults to ``rustfs.{{ LMS_HOST }}``. Add the DNS
     record, or set ``RUSTFS_CONSOLE_HOST`` to your existing hostname.

   The data directory also moves from ``data/minio`` to ``data/rustfs``.

4. Apply and provision::

       tutor config save
       tutor local launch

5. Re-import your objects::

       mc mirror ./backup/openedx/ rustfs/openedx/

Testing
-------

See `TESTING.rst <TESTING.rst>`_ for the full procedure, from unit tests
through to a live S3 conformance run against a deployed stack.

::

    pip install -e ".[dev]"
    make test

License
-------

This work is licensed under the terms of the `GNU Affero General Public License
(AGPL) <https://www.gnu.org/licenses/agpl-3.0.en.html>`_.

Maintained by
--------------

This Tutor plugin is maintained by Syed Ali Abbas from
`Edly <https://edly.io>`__. Community support is available from the official
`Open edX forum <https://discuss.openedx.org>`__. Do you need help with this
plugin? See the `troubleshooting
<https://docs.tutor.edly.io/troubleshooting.html>`__ section from the Tutor
documentation.
