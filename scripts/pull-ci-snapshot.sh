#!/usr/bin/env bash
# Download the latest retained canonical CI snapshot, then invoke the explicit
# local replacement command. Requires GitHub CLI authentication with artifact read access.
set -euo pipefail

replace=false
if [[ "${1:-}" == "--replace" ]]; then
  replace=true
  shift
fi
if [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--replace]" >&2
  exit 2
fi

repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
artifact_record="$(gh api --paginate --slurp "repos/${repo}/actions/artifacts?per_page=100" | jq -r '[.[].artifacts[] | select(.name == "bia-database-canonical" and .expired == false)] | sort_by(.created_at) | reverse | .[0] | select(.) | [.id, .workflow_run.id] | @tsv')" || {
  echo "Unable to list canonical CI artifacts." >&2
  exit 1
}
if [[ -z "$artifact_record" ]]; then
  echo "No retained canonical CI artifact exists yet; legacy artifacts are not used for local sync." >&2
  exit 1
fi
IFS=$'\t' read -r artifact_id run_id <<< "$artifact_record"

download_dir="$(mktemp -d)"
trap 'rm -rf "$download_dir"' EXIT
echo "Downloading canonical artifact $artifact_id from run: $run_id"
if ! gh run download "$run_id" -n bia-database-canonical -D "$download_dir"; then
  echo "Canonical artifact retrieval failed; local database was not changed." >&2
  exit 1
fi

snapshot="$(find "$download_dir" -type f -name bia-latest.db -print -quit)"
if [[ -z "$snapshot" ]]; then
  echo "Canonical bia-latest.db was not present in the downloaded artifact." >&2
  exit 1
fi

args=(--source "$snapshot")
if [[ "$replace" == true ]]; then
  args+=(--replace)
fi
python backend/sync_ci_snapshot.py "${args[@]}"
