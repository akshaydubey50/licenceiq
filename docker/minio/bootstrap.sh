#!/bin/sh
set -eu

# Compose waits for MinIO on `up`; this bounded retry also makes `compose start`
# reliable when it resumes already-created containers.
attempt=0
until mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "MinIO did not become available within 60 seconds." >&2
    exit 1
  fi
  sleep 1
done
mc mb --ignore-existing local/licenceiq-private
mc admin policy create local licenceiq-app /policies/licenceiq-app-policy.json
mc admin user add local "$MINIO_APP_ACCESS_KEY" "$MINIO_APP_SECRET_KEY"
mc admin policy attach local licenceiq-app --user "$MINIO_APP_ACCESS_KEY"
