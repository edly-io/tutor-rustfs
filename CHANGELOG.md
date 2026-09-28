# Changelog

<!-- scriv-insert-here -->

## Unreleased

- [Feature] Initial release. `tutor-rustfs` provides S3-compatible object
  storage for Open edX backed by [RustFS](https://github.com/rustfs/rustfs),
  succeeding `tutor-minio` now that MinIO is archived upstream.

  Feature parity with `tutor-minio` is intentional — same buckets, same ports,
  same `mc` tooling, same bucket policies, same `discovery` and `xqueue`
  integrations — with the following differences:

  - 💥 **No gateway mode.** There is no `RUSTFS_GATEWAY` setting. MinIO
    removed gateway mode in 2022 and RustFS never had it. Use
    [tutor-contrib-s3](https://github.com/cleura/tutor-contrib-s3) for
    external S3 providers. Azure Blob Storage has no supported path today.
  - 💥 **Config keys are `RUSTFS_`-prefixed.** Every `MINIO_*` key has a
    `RUSTFS_*` equivalent with the same default value. `MC_DOCKER_IMAGE`,
    which `tutor-minio` registered unprefixed in the global Tutor namespace,
    is now `RUSTFS_MC_DOCKER_IMAGE`.
  - 💥 **The console lives at a path.** RustFS serves the S3 API at `/` on
    port 9001 and mounts the console under `/rustfs/console/`. The
    `caddyfile` patch redirects, so `http://<RUSTFS_CONSOLE_HOST>` works; in
    development mode use the full path.
  - 💥 **The server runs as non-root UID 10001.** On a fresh Linux install the
    data directory must be created and chowned before the first start, or
    RustFS aborts with `Permission denied (os error 13)`.
  - 💥 **`RUSTFS_CONSOLE_HOST` defaults to `rustfs.{{ LMS_HOST }}`**, not
    `minio.{{ LMS_HOST }}`. Add the DNS record or override the setting.
  - 💥 **The data directory moved** from `data/minio` to `data/rustfs`.
  - 💥 **No in-place migration from MinIO.** RustFS cannot read a MinIO data
    directory in the stock image; MinIO on-disk compatibility is gated behind
    the `rio-v2` cargo feature and is not part of the default build. Export
    with `mc mirror` before switching. See the README.
  - This plugin and `tutor-minio` cannot be enabled simultaneously; doing so
    raises an error rather than producing a subtly broken stack.

- [Security] The public bucket is now created with `mc policy set download`
  (anonymous read) instead of `mc policy set public`. In `mc`'s policy
  vocabulary `public` means anonymous read **and write**: on a deployment
  whose S3 endpoint is reachable from the internet, anyone could upload
  objects to and delete objects from the main Open edX bucket without
  credentials. `tutor-minio` uses `public` and is affected. Verified against
  RustFS 1.0.0: with `public`, an unauthenticated `PUT` returns 200 and an
  unauthenticated `DELETE` returns 204; with `download`, both return 403
  while anonymous `GET` still returns 200.

- [Improvement] Add `RUSTFS_REGION` (default `us-east-1`, matching RustFS's
  own default), passed to both the server and Open edX's
  `AWS_S3_REGION_NAME`.

- [Improvement] Add a test suite covering plugin registration, template
  rendering, YAML and Django-settings validity, the init-job naming contract,
  bucket coverage, and cross-plugin integration — plus an opt-in live S3
  conformance suite. See `TESTING.rst`.
