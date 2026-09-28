#!/usr/bin/env bash
# Interface languages (NF-13): extract every marked string into tellybox/locale/messages.pot
# and merge it into the Dutch and German catalogs. Then translate the new or changed entries
# (empty msgstr, or marked fuzzy) in tellybox/locale/{nl,de}/LC_MESSAGES/messages.po.
# tests/test_i18n.py fails while any string is untranslated.
set -euo pipefail
cd "$(dirname "$0")/.."
PYBABEL="${PYBABEL:-.venv/bin/pybabel}"

"$PYBABEL" extract -F babel.cfg -k N_ -k Nn_:1,2 --sort-by-file --no-wrap \
  --project Tellybox --copyright-holder "Tellybox" --msgid-bugs-address "" \
  -o tellybox/locale/messages.pot .

for lang in nl de; do
  po="tellybox/locale/$lang/LC_MESSAGES/messages.po"
  if [[ -f "$po" ]]; then
    "$PYBABEL" update -i tellybox/locale/messages.pot -d tellybox/locale -l "$lang" --no-wrap
  else
    "$PYBABEL" init -i tellybox/locale/messages.pot -d tellybox/locale -l "$lang" --no-wrap
  fi
done
