#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 2 ]]; then
  echo "Usage: $0 <source> <changed-feed-json> [changed-feed-json...]" >&2
  exit 64
fi

source="$1"
shift
changed_files=("$@")

: "${DOCSPACE_FEED_PUSH_ENDPOINT:?Missing DOCSPACE_FEED_PUSH_ENDPOINT}"
: "${DOCSPACE_FEED_PUSH_SECRET:?Missing DOCSPACE_FEED_PUSH_SECRET}"

for file in "${changed_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "Feed file does not exist: $file" >&2
    exit 66
  fi
done

commit_sha="$(git rev-parse HEAD)"

if [[ "${#changed_files[@]}" -eq 1 ]]; then
  feed_version="$(sha256sum "${changed_files[0]}" | awk '{print $1}')"
else
  feed_version="$(
    for file in "${changed_files[@]}"; do
      sha256sum "$file"
    done | sha256sum | awk '{print $1}'
  )"
fi

changed_files_json="$(jq -n '$ARGS.positional' --args "${changed_files[@]}")"
payload="$(
  jq -n \
    --arg source "$source" \
    --arg target "feed" \
    --arg commitSha "$commit_sha" \
    --arg feedVersion "$feed_version" \
    --argjson changedFiles "$changed_files_json" \
    '{
      source: $source,
      target: $target,
      commitSha: $commitSha,
      feedVersion: $feedVersion,
      changedFiles: $changedFiles
    }'
)"

echo "Sending feed update push: source=$source commitSha=$commit_sha feedVersion=$feed_version files=${changed_files[*]}"

curl --fail-with-body \
  --request POST \
  --header "Authorization: Bearer ${DOCSPACE_FEED_PUSH_SECRET}" \
  --header "Content-Type: application/json" \
  --data "$payload" \
  "$DOCSPACE_FEED_PUSH_ENDPOINT"
