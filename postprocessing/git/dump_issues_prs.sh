# https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#list-pull-requests
# https://cli.github.com/manual/gh_help_formatting

PR_FIELDS=(
    number
    title
    author
    createdAt
    closedAt
    url
    isDraft
    baseRefName
)

ISSUE_FIELDS=(
    number
    title
    author
    createdAt
    closedAt
    url
)

gh pr list --limit 50 --state all --json "$(IFS=,; echo "${PR_FIELDS[*]}")" >> prs.json
gh issue list --limit 50 --json "$(IFS=,; echo "${ISSUE_FIELDS[*]}")" >> issues.json
