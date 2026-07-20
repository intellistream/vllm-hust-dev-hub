#!/usr/bin/env bash
# Shared container-name resolution for quickstart and container helpers.

docker_container_name_is_valid() {
  local name="$1"

  (( ${#name} <= 255 )) && [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]+$ ]]
}

container_name_from_image_and_user() {
  local image="$1"
  local login_user="$2"
  local image_name
  local normalized_user
  local max_name_length=255
  local max_user_length
  local max_image_length

  image_name="${image##*/}"
  image_name="${image_name%%@*}"
  image_name="$(printf '%s' "$image_name" | sed -E 's/[^A-Za-z0-9_.-]+/-/g; s/^-+//; s/-+$//')"
  normalized_user="$(printf '%s' "$login_user" | sed -E 's/[^A-Za-z0-9_.-]+/-/g; s/^-+//; s/-+$//')"

  [[ -n "$image_name" ]] || image_name="vllm-ascend"
  [[ -n "$normalized_user" ]] || normalized_user="user"

  # Keep the login suffix even when unusually long registry/image components
  # need truncation; the suffix is what differentiates per-user defaults.
  max_user_length=$((max_name_length - 2))
  normalized_user="${normalized_user:0:max_user_length}"
  max_image_length=$((max_name_length - ${#normalized_user} - 1))
  image_name="${image_name:0:max_image_length}"
  printf '%s-%s\n' "$image_name" "$normalized_user"
}

configured_vllm_engine_container_name() {
  if [[ -n "${VLLM_ENGINE_CONTAINER_NAME:-}" ]]; then
    if [[ -n "${VLLM_ENGINE_CONTAINER:-}" && "$VLLM_ENGINE_CONTAINER" != "$VLLM_ENGINE_CONTAINER_NAME" ]]; then
      printf '[container] VLLM_ENGINE_CONTAINER_NAME overrides deprecated VLLM_ENGINE_CONTAINER.\n' >&2
    fi
    printf '%s\n' "$VLLM_ENGINE_CONTAINER_NAME"
    return 0
  fi

  if [[ -n "${VLLM_ENGINE_CONTAINER:-}" ]]; then
    printf '[container] VLLM_ENGINE_CONTAINER is deprecated; use VLLM_ENGINE_CONTAINER_NAME instead.\n' >&2
    printf '%s\n' "$VLLM_ENGINE_CONTAINER"
    return 0
  fi

  if [[ -n "${CONTAINER_NAME:-}" ]]; then
    printf '%s\n' "$CONTAINER_NAME"
    return 0
  fi

  return 1
}

validate_docker_container_name() {
  local name="$1"

  if docker_container_name_is_valid "$name"; then
    return 0
  fi

  printf '[container] Invalid container name %q. Use 2-255 characters; start with a letter or digit and use only letters, digits, periods, underscores, or hyphens.\n' "$name" >&2
  return 1
}
