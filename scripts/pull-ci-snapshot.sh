#!/usr/bin/env bash
# Download the latest successful CI snapshot, then invoke the explicit local
# replacement command. Requires GitHub CLI authentication with artifact read access.
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

run_id="$(gh run list --workflow=collect.yml --status=success --limit=1 --json databaseId --jq '.[0].databaseId')"
if [[ -z "$run_id" ]]; then
  echo "No successful collection run with a canonical snapshot was found." >&2
  exit 1
fi

download_dir="$(mktemp -d)"
trap 'rm -rf "$download_dir"' EXIT
echo "Downloading canonical snapshot from successful run: $run_id"
gh run download "$run_id" -n bia-database-backup -D "$download_dir"

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
