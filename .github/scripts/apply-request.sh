#!/usr/bin/env bash
# Apply an accepted "Game Settings Update" request and publish it.
#
#   apply-request.sh <issue number>
#
# Needs: gh (authenticated), python3 with jsonschema, a checkout of main, and
# the upstream XML at $UPSTREAM_XML. With DRY_RUN=1 it stops before pushing,
# commenting or editing the issue and prints what it would do.
set -euo pipefail

ISSUE=$1
REPO=${GITHUB_REPOSITORY:-BlitterStudio/amiberry-game-db}
ACTOR=${GITHUB_ACTOR:-$(gh api user --jq .login)}
UPSTREAM_XML=${UPSTREAM_XML:-/tmp/whdload_db.xml}
WORK=$(mktemp -d)

say() {  # post a comment (or print it in a dry run)
  if [ "${DRY_RUN:-0}" = 1 ]; then echo "--- comment on #$ISSUE ---"; cat "$1"; else
    gh issue comment "$ISSUE" -R "$REPO" --body-file "$1"; fi
}

drop_label() {
  if [ "${DRY_RUN:-0}" = 1 ]; then echo "--- would remove label accepted"; else
    gh issue edit "$ISSUE" -R "$REPO" --remove-label accepted; fi
}

state=$(gh issue view "$ISSUE" -R "$REPO" --json state --jq .state)
if [ "$state" != OPEN ]; then
  echo "#$ISSUE is $state; nothing to do"
  exit 0
fi

pushed=0
for attempt in 1 2 3 4 5; do
  if [ "${DRY_RUN:-0}" != 1 ]; then
    git fetch -q origin main
    git reset -q --hard origin/main
  fi

  python3 converter/xml_to_json.py "$UPSTREAM_XML" "$WORK/base.json" > /dev/null

  status=0
  python3 converter/triage_issue.py --issue "$ISSUE" --apply --require-clean \
    --output "$WORK/triage.md" > /dev/null || status=$?
  if [ "$status" -eq 4 ]; then
    { cat "$WORK/triage.md"; echo; echo "The \`accepted\` label was removed. Fix the request or the database, then add it again."; } > "$WORK/msg.md"
    say "$WORK/msg.md"
    drop_label
    exit 0
  elif [ "$status" -ne 0 ]; then
    exit "$status"
  fi

  python3 converter/xml_to_json.py "$UPSTREAM_XML" "$WORK/new.json" --report "$WORK/convert.md" > /dev/null
  if ! python3 converter/check_overrides.py "$WORK/new.json" --schema schema/whdload_db.schema.json \
       --report "$WORK/check.md" > /dev/null; then
    { echo "Not applied: the checks failed with these changes."; echo; sed '/^<details>/,$d' "$WORK/check.md"; } > "$WORK/msg.md"
    say "$WORK/msg.md"
    drop_label
    git checkout -q -- builder
    git clean -qfd builder
    exit 1
  fi
  python3 converter/diff_db.py "$WORK/base.json" "$WORK/new.json" > "$WORK/diff.md"

  git add builder
  git -c user.name="github-actions[bot]" -c user.email="github-actions[bot]@users.noreply.github.com" \
    commit -q -m "Apply settings from #$ISSUE" -m "Accepted by @$ACTOR."
  if [ "${DRY_RUN:-0}" = 1 ]; then
    echo "--- would push:"; git show --stat --format='%s%n%b' HEAD
    pushed=1
    break
  fi
  if git push -q origin HEAD:main; then
    pushed=1
    break
  fi
  echo "push rejected (attempt $attempt); retrying on the new main"
  sleep $((attempt * 5))
done

if [ "$pushed" != 1 ]; then
  echo "could not push after 5 attempts" >&2
  exit 1
fi

sha=$(git rev-parse --short HEAD)
{
  echo "Applied in $sha (accepted by @$ACTOR). The sync workflow publishes it to \`whdload_db.json\` in a few minutes; Amiberry users get it from **Update WHDBooter files** and in the next release."
  echo
  echo "### Database changes"
  echo
  cat "$WORK/diff.md"
} > "$WORK/msg.md"

if [ "${DRY_RUN:-0}" = 1 ]; then
  say "$WORK/msg.md"
  echo "--- would run sync.yml and close #$ISSUE"
  exit 0
fi
gh workflow run sync.yml -R "$REPO" --ref main
say "$WORK/msg.md"
gh issue close "$ISSUE" -R "$REPO" --reason completed
