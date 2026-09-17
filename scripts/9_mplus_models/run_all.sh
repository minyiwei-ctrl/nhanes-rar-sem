#!/bin/bash
# Run every .inp in this directory through Mplus and flag errors and
# negative factor loadings.
#
#   bash run_all.sh                 # every .inp
#   bash run_all.sh 'm_*.inp'       # a subset
#   MPLUS=/path/to/mplus bash run_all.sh
#
# Locates the Mplus executable itself; no PATH setup needed.

set -u
cd "$(dirname "$0")"
PATTERN="${1:-*.inp}"

# Locate Mplus
find_mplus() {
    [ -n "${MPLUS:-}" ] && [ -x "$MPLUS" ] && { echo "$MPLUS"; return; }
    command -v mplus >/dev/null && { command -v mplus; return; }
    for p in \
        "/Applications/Mplus/mplus" \
        "/Applications/Mplus Demo/mplus" \
        "/Applications/MplusDemo/mplus" \
        "$HOME/Mplus/mplus" \
        "/usr/local/bin/mplus" \
        "/opt/mplus/mplus"
    do
        [ -x "$p" ] && { echo "$p"; return; }
    done
    # Last resort: search /Applications up to three levels deep.
    found=$(find /Applications -maxdepth 3 -name 'mplus' -type f -perm -u+x 2>/dev/null | head -1)
    [ -n "$found" ] && echo "$found"
}

MP=$(find_mplus)
if [ -z "$MP" ]; then
    cat <<'EOF'
Could not find Mplus.

Look for it:
    ls /Applications | grep -i mplus
    find /Applications -maxdepth 3 -iname 'mplus*' -type f 2>/dev/null

Then either run with an explicit path:
    MPLUS="/Applications/Mplus/mplus" bash run_all.sh

or add it to PATH for this shell (note: no line break inside the quotes):
    export PATH="/Applications/Mplus:$PATH"
EOF
    exit 1
fi
echo "using: $MP"
echo

# Run
pass=0; fail=0; warn=0
for f in $PATTERN; do
    stem="${f%.inp}"
    printf '%-30s ' "$stem"
    "$MP" "$f" "$stem.out" >/dev/null 2>&1

    if [ ! -f "$stem.out" ]; then
        echo "NO OUTPUT"; fail=$((fail+1)); continue
    fi

    n=$(grep -m1 'Number of observations' "$stem.out" | grep -oE '[0-9]+$')
    err=$(grep -c '^\*\*\* ERROR' "$stem.out")

    # COG@1 identifies the factor only up to sign; a mirror solution flips every
    # coefficient on COG. l1 > 0 in the input should prevent it, and negative
    # STDYX loadings are flagged here as a check.
    note=""
    if grep -q 'COG *BY' "$stem.out"; then
        neg=$(sed -n '/STDYX Standardization/,/R-SQUARE/p' "$stem.out" \
              | sed -n '/COG *BY/,/^ *$/p' | grep -cE '^ +[A-Z_0-9]+ +-')
        if [ "$neg" -gt 0 ]; then note="  *** NEGATIVE LOADINGS ***"; warn=$((warn+1)); fi
    fi

    if [ "$err" -gt 0 ]; then
        echo "ERROR in output"; fail=$((fail+1))
    else
        echo "n=${n:-?}${note}"; pass=$((pass+1))
    fi
done

echo
echo "ran $((pass+fail)): $pass ok, $fail failed, $warn with negative loadings"
[ "$warn" -gt 0 ] && echo "Do not read any COG coefficient until the loadings are positive."
exit 0
