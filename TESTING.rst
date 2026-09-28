Testing tutor-rustfs
====================

Four tiers, cheapest first. Each catches a different class of bug, and
the earlier ones run in seconds — work down the list rather than jumping
straight to a full deployment.

.. contents::
   :local:
   :depth: 1

Tier 1 — static checks and template rendering
---------------------------------------------

No Docker, no Open edX, runs in under a second. This is what CI runs on
every pull request.

::

    pip install -e ".[dev]"
    make test

That runs lint, formatting, type checks, and the unit suite. The unit
suite alone::

    make test-unit

What it covers:

- The ``tutor.plugin.v1`` entry point resolves and Tutor can load the
  plugin (a typo in ``pyproject.toml`` fails here).
- Every config key is ``RUSTFS_``-prefixed and no ``MINIO_`` key
  survives.
- Every patch renders against the default config with no undefined
  variables and no leftover Jinja.
- YAML patches parse; Django-settings patches compile.
- The init-job service is named ``rustfs-job``, matching the service
  registered with ``CLI_DO_INIT_TASKS`` — Tutor appends the ``-job``
  suffix, and a mismatch makes ``tutor local do init`` fail with an
  unhelpful "no such service".
- Every bucket Open edX is configured to write to is created by
  ``init.sh``.
- The ``discovery`` and ``xqueue`` cross-plugin patches point at RustFS.
- Enabling this plugin alongside ``tutor-minio`` raises an error.

To confirm the suite is not passing vacuously, break something on
purpose and check it goes red::

    sed -i 's/^rustfs-job:/minio-job:/' \
        tutorrustfs/patches/local-docker-compose-jobs-services
    make test-unit   # expect failures
    git checkout tutorrustfs/patches/local-docker-compose-jobs-services

Tier 2 — generated configuration
---------------------------------

Checks that Tutor produces a valid stack, without starting it. Use a
throwaway root so your real deployment is untouched::

    export TUTOR_ROOT=/tmp/tutor-rustfs-test
    tutor plugins enable rustfs
    tutor config save
    tutor local dc config > /dev/null && echo "compose OK"

Then read the rendered output::

    tutor config printvalue RUSTFS_HOST
    tutor config printvalue RUSTFS_DOCKER_IMAGE
    grep -A20 '^  rustfs:' "$TUTOR_ROOT/env/local/docker-compose.yml"

For Kubernetes::

    tutor k8s apply --dry-run=client -f "$TUTOR_ROOT/env/k8s/deployments.yml"

Tier 3 — live deployment
-------------------------

A real stack. On a **Linux host**, create the data directory first or
RustFS will abort with ``Permission denied (os error 13)``::

    mkdir -p "$(tutor config printroot)/data/rustfs"
    sudo chown -R 10001:10001 "$(tutor config printroot)/data/rustfs"

Then::

    tutor local launch

Checks, in order:

1. **The server is up.**

   ::

       tutor local logs rustfs --tail 50
       tutor local exec rustfs rustfs --version

2. **Buckets exist and the init task is idempotent.** Run it twice; the
   second run must also succeed.

   ::

       tutor local do init --limit=rustfs
       tutor local do init --limit=rustfs

3. **The console loads.** Visit ``http://<RUSTFS_CONSOLE_HOST>``. It
   should redirect to ``/rustfs/console/`` and render a UI, *not* an
   XML ``AccessDenied`` document. Log in with::

       tutor config printvalue OPENEDX_AWS_ACCESS_KEY
       tutor config printvalue OPENEDX_AWS_SECRET_ACCESS_KEY

4. **Data survives a restart.** Upload something, then::

       tutor local restart rustfs

   and confirm it is still there. This catches a volume that was never
   actually persisted.

5. **Open edX can write.** Upload a course asset in Studio and confirm
   it appears in the ``openedx`` bucket. Then upload a video and confirm
   it lands in ``openedxvideos`` — video goes through the multipart
   path, which fails differently from small uploads.

Tier 4 — S3 conformance
------------------------

The live boto3 suite, using the same client configuration Open edX
uses. It is skipped unless ``RUSTFS_TEST_ENDPOINT`` is set.

::

    pip install boto3 requests
    export RUSTFS_TEST_ENDPOINT=http://localhost:9000
    export RUSTFS_TEST_ACCESS_KEY="$(tutor config printvalue OPENEDX_AWS_ACCESS_KEY)"
    export RUSTFS_TEST_SECRET_KEY="$(tutor config printvalue OPENEDX_AWS_SECRET_ACCESS_KEY)"
    pytest -v tests/test_s3_conformance.py

Covers signed PUT/GET, ``HEAD``, presigned download URLs, a 6 MiB
multipart upload, ``ListObjectsV2``, server-side copy, delete, and an
anonymous read against the public bucket.

.. note::

   In production mode port 9000 is not published on the host; Caddy
   proxies it. Point ``RUSTFS_TEST_ENDPOINT`` at ``https://<RUSTFS_HOST>``
   instead, or run in development mode where the port is bound to
   localhost.

Cross-plugin checks
-------------------

The failure mode these catch is patch ordering: two plugins both writing
``STORAGES["default"]``, and the last one winning. Rendering tests catch
it; a single-plugin smoke test does not.

::

    tutor plugins enable discovery
    tutor config save
    tutor local launch

- **discovery** — confirm the ``discoveryuploads`` bucket was created
  and that discovery's settings point at ``RUSTFS_HOST``.
- **xqueue** — confirm uploads land under the ``xqueueuploads`` prefix
  in the ``openedx`` bucket.
- **mfe** — confirm asset URLs resolve through the S3 host.

Verify the storage backend actually took effect::

    tutor local exec lms python -c \
        "from django.conf import settings; \
         print(settings.STORAGES['default']['BACKEND']); \
         print(settings.AWS_S3_ENDPOINT_URL)"

Known failure modes
-------------------

.. list-table::
   :header-rows: 1

   * - Symptom
     - Cause
   * - ``Permission denied (os error 13)`` on startup
     - Data directory owned by root. Chown it to ``10001:10001``.
   * - Console shows ``AccessDenied`` XML
     - Reached port 9001 at ``/``. The console is at ``/rustfs/console/``.
   * - ``SignatureDoesNotMatch``
     - Access key or secret differs between the server and Open edX.
   * - Uploads fail with a checksum error
     - The ``request_checksum_calculation`` setting was removed from
       ``openedx-common-settings``.
   * - ``NoSuchBucket`` on first upload
     - ``tutor local do init`` never ran, or ran against a different
       instance.
   * - ``tutor local do init`` says no such service
     - The job service name no longer matches the ``CLI_DO_INIT_TASKS``
       registration. Tier 1 catches this.
