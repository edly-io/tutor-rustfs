# Provision buckets on RustFS.
#
# Uses `rc`, RustFS's own S3-compatible CLI (see the RUSTFS_RC_DOCKER_IMAGE
# setting). The alias name is local to `rc` and has no bearing on how Open
# edX reaches the store — that goes through RUSTFS_HOST.
#
# This task is idempotent: `rc mb --ignore-existing` and `rc anonymous
# set` can both be re-run safely.
rc alias set rustfs http://rustfs:9000 {{ OPENEDX_AWS_ACCESS_KEY }} {{ OPENEDX_AWS_SECRET_ACCESS_KEY }}

rc mb --ignore-existing rustfs/{{ RUSTFS_BUCKET_NAME }}
rc mb --ignore-existing rustfs/{{ RUSTFS_FILE_UPLOAD_BUCKET_NAME }}
rc mb --ignore-existing rustfs/{{ RUSTFS_VIDEO_UPLOAD_BUCKET_NAME }}
rc mb --ignore-existing rustfs/{{ RUSTFS_GRADES_BUCKET_NAME }}
rc mb --ignore-existing rustfs/{{ RUSTFS_OPENEDX_LEARNING_BUCKET_NAME }}

# Make the common bucket world-*readable* (e.g. for forum image
# uploads served to browsers).
#
# `download` grants anonymous GET only. Do not use `public`: in rc's
# anonymous-access vocabulary that means read *and write*, which lets
# anyone who can reach RUSTFS_HOST upload to and delete from this
# bucket without credentials. tutor-minio used `public` here; that was
# a mistake.
rc anonymous set download rustfs/{{ RUSTFS_BUCKET_NAME }}

# Discovery bucket, only when the discovery plugin is enabled.
{% if RUSTFS_DISCOVERY_BUCKET_NAME %}
rc mb --ignore-existing rustfs/{{ RUSTFS_DISCOVERY_BUCKET_NAME }}
rc anonymous set download rustfs/{{ RUSTFS_DISCOVERY_BUCKET_NAME }}
{% endif %}
