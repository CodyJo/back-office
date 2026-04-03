#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/merm/projects/back-office/ops/forgejo-local"
RUNNER_DATA_DIR="${RUNNER_DATA_DIR:-${ROOT}/data/runner}"
RUNNER_IMAGE="${RUNNER_IMAGE:-data.forgejo.org/forgejo/runner:11}"
RUNNER_NAME="${RUNNER_NAME:-codyjo-local-runner}"
RUNNER_SCOPE="${RUNNER_SCOPE:-CodyJo}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,linux,docker}"
FORGEJO_INSTANCE_URL="${FORGEJO_INSTANCE_URL:-http://forgejo:3000}"
FORGEJO_CONTAINER="${FORGEJO_CONTAINER:-forgejo-local}"
FORGEJO_COMPOSE_DIR="${FORGEJO_COMPOSE_DIR:-${ROOT}}"
FORGEJO_NETWORK="${FORGEJO_NETWORK:-forgejo-local_default}"

mkdir -p "${RUNNER_DATA_DIR}"

if [[ ! -f "${RUNNER_DATA_DIR}/config.yml" ]]; then
  docker run --rm \
    -u 1000:1000 \
    -v "${RUNNER_DATA_DIR}:/data" \
    "${RUNNER_IMAGE}" \
    /bin/sh -lc 'forgejo-runner generate-config > /data/config.yml'
fi

if grep -q 'docker_host: "-"' "${RUNNER_DATA_DIR}/config.yml"; then
  perl -0pi -e 's/docker_host:\s*"-"/docker_host: "automount"/g' "${RUNNER_DATA_DIR}/config.yml"
fi

if [[ ! -f "${RUNNER_DATA_DIR}/.runner" ]]; then
  token="$(docker exec "${FORGEJO_CONTAINER}" forgejo actions generate-runner-token --scope "${RUNNER_SCOPE}")"
  docker run --rm \
    -u 1000:1000 \
    --network "${FORGEJO_NETWORK}" \
    -v "${RUNNER_DATA_DIR}:/data" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    "${RUNNER_IMAGE}" \
    forgejo-runner register \
      --no-interactive \
      --config /data/config.yml \
      --instance "${FORGEJO_INSTANCE_URL}" \
      --token "${token}" \
      --name "${RUNNER_NAME}" \
      --labels "${RUNNER_LABELS}"
fi

docker compose -f "${FORGEJO_COMPOSE_DIR}/compose.yaml" up -d runner
echo "Forgejo runner bootstrap complete."
