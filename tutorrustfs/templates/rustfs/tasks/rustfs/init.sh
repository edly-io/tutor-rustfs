# Provision buckets on RustFS.
#
# RustFS is wire-compatible with the MinIO `mc` client, so this runs
# from the `mc` image (see the RUSTFS_MC_DOCKER_IMAGE setting). The
# alias name is local to `mc` and has no bearing on how Open edX
# reaches the store — that goes through RUSTFS_HOST.
#
# This task is idempotent: `mc mb --ignore-existing` and `mc policy
# set` can both be re-run safely.
mc config host add rustfs http://rustfs:9000 {{ OPENEDX_AWS_ACCESS_KEY }} {{ OPENEDX_AWS_SECRET_ACCESS_KEY }} --api s3v4

mc mb --ignore-existing rustfs/{{ RUSTFS_BUCKET_NAME }} rustfs/{{ RUSTFS_FILE_UPLOAD_BUCKET_NAME }} rustfs/{{ RUSTFS_VIDEO_UPLOAD_BUCKET_NAME }} rustfs/{{ RUSTFS_GRADES_BUCKET_NAME }} rustfs/{{ RUSTFS_OPENEDX_LEARNING_BUCKET_NAME }}

# Make the common bucket world-*readable* (e.g. for forum image
# uploads served to browsers).
#
# `download` grants anonymous GET only. Do not use `public`: in mc's
# policy vocabulary that means read *and write*, which lets anyone who
# can reach RUSTFS_HOST upload to and delete from this bucket without
# credentials. tutor-minio used `public` here; that was a mistake.
mc policy set download rustfs/{{ RUSTFS_BUCKET_NAME }}

# Discovery bucket, only when the discovery plugin is enabled.
{% if RUSTFS_DISCOVERY_BUCKET_NAME %}
mc mb --ignore-existing rustfs/{{ RUSTFS_DISCOVERY_BUCKET_NAME }}
mc policy set download rustfs/{{ RUSTFS_DISCOVERY_BUCKET_NAME }}
{% endif %}
