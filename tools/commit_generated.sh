#!/usr/bin/env bash
# Commit regenerated artifacts to main, last-writer-wins.
#
# Four workflows rebuild the same outputs (docs/index.html,
# data/actuals_daily.json, state/state.json, config/*.json). When two land close
# together the loser's `git pull --rebase` hits a *content conflict* on those
# files and the run fails after having done all its real work — which is how the
# regulations scrape managed to fetch correctly and still report failure twice.
#
# Rebasing is the wrong model for generated output: there is nothing to merge,
# the fresher build simply wins. So on a rejected push, reset onto the new
# origin/main (keeping our files on disk), re-stage only our files, and commit
# again. Files this run didn't touch keep whatever the other writer put there.
#
# Usage: tools/commit_generated.sh "commit message" path [path ...]
set -uo pipefail

MSG="${1:?commit message required}"; shift
FILES=("$@")
[ "${#FILES[@]}" -gt 0 ] || { echo "no paths given" >&2; exit 2; }

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

stage() {
  for f in "${FILES[@]}"; do
    [ -e "$f" ] && git add -- "$f"
  done
  return 0
}

stage
if git diff --cached --quiet; then
  echo "nothing to commit"; exit 0
fi
git commit -q -m "$MSG"

for i in 1 2 3 4 5; do
  if git push -q origin HEAD:main; then
    echo "pushed on attempt $i"; exit 0
  fi
  echo "push rejected (attempt $i) — replaying generated files onto latest main"
  git fetch -q origin main || true
  git reset -q --mixed FETCH_HEAD
  stage
  if git diff --cached --quiet; then
    echo "remote already matches our output; nothing to do"; exit 0
  fi
  git commit -q -m "$MSG"
  sleep $((i * 3))
done

echo "could not push after 5 attempts" >&2
exit 1
