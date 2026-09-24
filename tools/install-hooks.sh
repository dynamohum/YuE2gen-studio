#!/bin/sh
# Put the repository's git hooks in place. Hooks are not copied by a clone, so each
# checkout runs this once.
set -e
cd "$(dirname "$0")/.."
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/sh
# Refuse a commit that carries a key. See tools/check_secrets.py.
exec python3 "$(git rev-parse --show-toplevel)/tools/check_secrets.py"
HOOK
chmod +x .git/hooks/pre-commit
echo "pre-commit hook installed: commits are checked for keys"
