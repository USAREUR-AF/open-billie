#!/usr/bin/env bash
# Records site/captures/validate.txt, shown on the landing page: the real kid
# validator run on the synthetic OETF example. Its shell trace line (+ ...) is
# left out, and the checkout's absolute path in
# the output is shown as "open-billie".
#
#   bash site/captures/capture-validate.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
{
  echo '$ bash deploy/bin/billie kid validate kids/examples/oetf'
  bash deploy/bin/billie kid validate kids/examples/oetf 2>&1 | grep -v '^+ '
} | sed "s#$root#open-billie#g" > site/captures/validate.txt
echo "wrote site/captures/validate.txt"
