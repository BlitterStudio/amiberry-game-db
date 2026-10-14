#!/usr/bin/env bash
# Apply an accepted "Game Settings Update" request and publish it.
#
#   apply-request.sh <issue number>
#
# Needs: gh (authenticated), python3 with jsonschema, a checkout of main, and
# the upstream XML at $UPSTREAM_XML.
#
# ISSUE_BODY_FILE: the issue body as it was when the request was accepted (the
#   labeled event's payload). The run applies exactly that text and refuses if
#   the issue was edited, or lost the `accepted` label, before the push.
#   Without it (manual runs) the current body is used.
# REQUIRE_LABEL=1: also require the `accepted` label at push time.
# DRY_RUN=1: stop before pushing, commenting or editing the issue, and print
#   what would happen.
set -euo pipefail

ISSUE=$1
REPO=${GITHUB_REPOSITORY:-BlitterStudio/amiberry-game-db}
ACTOR=${GITHUB_ACTOR:-$(gh api user --jq .login)}
UPSTREAM_XML=${UPSTREAM_XML:-/tmp/whdload_db.xml}
WORK=$(mktemp -d)
APPLY_SUBJECT="Apply settings from #$ISSUE"

dry() { [ "${DRY_RUN:-0}" = 1 ]; }

retry() {  # GitHub API calls after the push must not strand a pushed commit
  local n
  for n in 1 2 3 4; do
    "$@" && return 0
    sleep $((n * 10))
  done
  return 1
}

say() {
  if dry; then echo "--- comment on #$ISSUE ---"; cat "$1"; else
    retry gh issue comment "$ISSUE" -R "$REPO" --body-file "$1"; fi
}

drop_label() {
  if dry; then echo "--- would remove label accepted"; else
    gh issue edit "$ISSUE" -R "$REPO" --remove-label accepted || true; fi
}

current_body() { gh issue view "$ISSUE" -R "$REPO" --json body --jq .body; }

publish() {  # $1 = commit, $2 = file with the database changes (may be empty)
  local close=1
  [ -s "$WORK/notes.md" ] && close=0
  {
    echo "Applied in $1 (accepted by @$ACTOR). The sync workflow publishes it to \`whdload_db.json\` in a few minutes; Amiberry users get it from **Update WHDBooter files** and in the next release."
    if [ -s "$2" ]; then echo; echo "### Database changes"; echo; cat "$2"; fi
    if [ "$close" = 0 ]; then
      echo
      echo "This request has Additional Notes, which the bot does not act on, so the issue stays open. Close it once nothing else is needed."
    fi
  } > "$WORK/msg.md"

  if dry; then
    say "$WORK/msg.md"
    echo "--- would run sync.yml$([ "$close" = 1 ] && echo " and close #$ISSUE")"
    return
  fi
  retry gh workflow run sync.yml -R "$REPO" --ref main
  say "$WORK/msg.md"
  if [ "$close" = 1 ]; then
    retry gh issue close "$ISSUE" -R "$REPO" --reason completed
  fi
}

state=$(gh issue view "$ISSUE" -R "$REPO" --json state --jq .state)
if [ "$state" != OPEN ]; then
  echo "#$ISSUE is $state; nothing to do"
  exit 0
fi

snapshot=$WORK/body.md
if [ -n "${ISSUE_BODY_FILE:-}" ]; then
  cp "$ISSUE_BODY_FILE" "$snapshot"
else
  current_body > "$snapshot"
fi

pushed=0
for attempt in 1 2 3 4 5; do
  if ! dry; then
    git fetch -q origin main
    git reset -q --hard origin/main
  fi

  python3 converter/xml_to_json.py "$UPSTREAM_XML" "$WORK/base.json" > /dev/null

  status=0
  # Plan against the database this run builds, not the committed copy, which
  # can be a day behind upstream (e.g. a newly added same-name archive).
  python3 converter/triage_issue.py --issue "$ISSUE" --db "$WORK/base.json" --body-file "$snapshot" \
    --apply --require-clean --notes-output "$WORK/notes.md" --output "$WORK/triage.md" > /dev/null || status=$?

  if [ "$status" -eq 5 ]; then
    # Nothing left to change. If an earlier run already pushed this request
    # but stopped before publishing, finish that run instead of refusing.
    # awk reads all of the log (no early exit) so git never gets SIGPIPE under pipefail.
    previous=$(git log --format='%h%x09%s' HEAD | awk -F'\t' -v s="$APPLY_SUBJECT" '$2 == s && !found { print $1; found = 1 }')
    if [ -n "$previous" ]; then
      echo "already applied in $previous; finishing publication"
      : > "$WORK/diff.md"
      publish "$previous" "$WORK/diff.md"
      exit 0
    fi
  fi
  if [ "$status" -eq 4 ] || [ "$status" -eq 5 ]; then
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

  # The approval covers the text that was accepted. Stop if the request was
  # edited or un-accepted while this run was queued or working.
  if ! dry; then
    current_body > "$WORK/current.md"
    if ! cmp -s "$snapshot" "$WORK/current.md"; then
      changed="the issue was edited after it was accepted"
    elif [ "${REQUIRE_LABEL:-0}" = 1 ] && \
         [ "$(gh issue view "$ISSUE" -R "$REPO" --json labels --jq '[.labels[].name] | index("accepted") != null')" != true ]; then
      changed="the \`accepted\` label was removed"
    else
      changed=""
    fi
    if [ -n "$changed" ]; then
      # shellcheck disable=SC2016  # literal backticks for Markdown
      printf 'Not applied: %s. Check the bot comment for the current request and add the `accepted` label again.\n' "$changed" > "$WORK/msg.md"
      say "$WORK/msg.md"
      drop_label
      git checkout -q -- builder
      git clean -qfd builder
      exit 0
    fi
  fi

  git add builder
  git -c user.name="github-actions[bot]" -c user.email="github-actions[bot]@users.noreply.github.com" \
    commit -q -m "$APPLY_SUBJECT" -m "Accepted by @$ACTOR."
  if dry; then
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

publish "$(git rev-parse --short HEAD)" "$WORK/diff.md"
