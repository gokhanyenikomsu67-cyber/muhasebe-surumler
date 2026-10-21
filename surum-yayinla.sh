#!/bin/sh
# Programın bu sürümünü herkese açık sürüm deposuna (muhasebe-surumler) koyar; kurulu programlar oradan güncellenir.
# Kullanım: ./surum-yayinla.sh <sürüm deposunun yerel kopyası>   (o kopyada sonra git add -A, commit, push)
# Ana depo gizli kalır: sürüm deposuna yalnız bu sürümün dosyaları gider, ana deponun geçmişi gitmez.
set -e
HEDEF=${1:?sürüm deposunun klasörü}
find "$HEDEF" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git archive HEAD | tar -x -C "$HEDEF"
git log -1 --format="%cs %h" > "$HEDEF/surum.txt"
grep -q "$(cat "$HEDEF/surum.txt")" "$HEDEF/backend/app/surum.py"
cat "$HEDEF/surum.txt"
