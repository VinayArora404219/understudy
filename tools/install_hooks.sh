#!/usr/bin/env bash
# Install the pre-commit guard: every commit is checked by tools/check_public.py.
set -e
cd "$(dirname "$0")/.."
printf '#!/bin/sh\nexec python3 tools/check_public.py\n' > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "pre-commit hook installed"
