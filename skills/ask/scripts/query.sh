#!/usr/bin/env bash
set -euo pipefail

# survey-any リポジトリのパスを ghq 経由で解決し、mise タスクを実行する

resolve_repo() {
  local repo_path
  repo_path=$(ghq list --full-path | grep 'survey-any$' | head -1)
  if [ -z "$repo_path" ]; then
    echo "Error: survey-any repository not found via ghq" >&2
    echo "Run: ghq get <survey-any-repo-url>" >&2
    exit 1
  fi
  echo "$repo_path"
}

REPO=$(resolve_repo)

cmd="${1:?Usage: query.sh <command> [args...]}"
shift

case "$cmd" in
  fm)
    mise -C "$REPO" run fm 2>/dev/null
    ;;
  fm-tags)
    mise -C "$REPO" run fm-tags 2>/dev/null
    ;;
  fm-related)
    mise -C "$REPO" run fm-related "${1:?Usage: query.sh fm-related <topic>}" 2>/dev/null
    ;;
  read)
    topic="${1:?Usage: query.sh read <topic-name>}"
    readme="$REPO/topics/$topic/README.md"
    if [ ! -f "$readme" ]; then
      echo "Error: $readme not found" >&2
      exit 1
    fi
    cat "$readme"
    ;;
  path)
    echo "$REPO"
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    echo "Commands: fm, fm-tags, fm-related, read, path" >&2
    echo "Note: tag-search / list は 'fm | jq ...' で合成してください" >&2
    exit 1
    ;;
esac
