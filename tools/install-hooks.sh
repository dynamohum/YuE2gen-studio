#!/bin/sh
# Use the repository's own hooks (tools/git-hooks): the pre-commit key check and the
# pre-push checks for GitHub. A clone does not carry git settings, so each checkout
# runs this once.
set -e
cd "$(dirname "$0")/.."
git config core.hooksPath tools/git-hooks
echo "hooks enabled from tools/git-hooks: commits and pushes to GitHub are checked for keys"
