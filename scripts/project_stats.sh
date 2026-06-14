#!/usr/bin/env bash
# BoutyHunter — Project Stats Generator
# Usage: ./scripts/project_stats.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "╔══════════════════════════════════════════╗"
echo "║     🎯 BoutyHunter — Project Stats       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ─── Source files (no .venv, no .git, no __pycache__) ──────────────
SRC_FILES=$(find . -maxdepth 5 \
    -not -path './.git/*' \
    -not -path './.venv/*' \
    -not -path './__pycache__/*' \
    -type f \( -name '*.py' -o -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.yaml' -o -name '*.yml' -o -name '*.toml' -o -name '*.md' \))

echo "── Source files ──"
total_src=$(echo "$SRC_FILES" | wc -l)
echo "  Total source files: $total_src"
echo ""

# ─── By language ───────────────────────────────────────────────────
echo "── By language ──"
declare -A LANG_MAP=(
    [py]="Python" [html]="HTML" [css]="CSS" [js]="JavaScript"
    [yaml]="YAML" [yml]="YAML" [toml]="TOML" [md]="Markdown"
)
echo "$SRC_FILES" | sed 's/.*\.//' | sort | uniq -c | sort -rn | while read count ext; do
    lang="${LANG_MAP[$ext]:-$ext}"
    printf "  %3d files   %-12s\n" "$count" "$lang ($ext)"
done
echo ""

# ─── Lines of code ────────────────────────────────────────────────
echo "── Lines of code ──"
total_loc=$(echo "$SRC_FILES" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}')
py_loc=$(find . -maxdepth 5 -not -path './.git/*' -not -path './.venv/*' -not -path './__pycache__/*' -type f -name '*.py' | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}')
html_loc=$(find . -maxdepth 5 -not -path './.git/*' -not -path './.venv/*' -not -path './__pycache__/*' -type f -name '*.html' | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}')
css_loc=$(find . -maxdepth 5 -not -path './.git/*' -not -path './.venv/*' -not -path './__pycache__/*' -type f -name '*.css' | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}')
echo "  Total:    ${total_loc:-0} lines"
echo "  Python:   ${py_loc:-0} lines"
echo "  HTML:     ${html_loc:-0} lines"
echo "  CSS:      ${css_loc:-0} lines"
echo ""

# ─── Per file (source only) ──────────────────────────────────────
echo "── Per file (source only, sorted by size) ──"
find . -maxdepth 5 \
    -not -path './.git/*' \
    -not -path './.venv/*' \
    -not -path './__pycache__/*' \
    -type f \( -name '*.py' -o -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.yaml' -o -name '*.yml' \) | xargs wc -l 2>/dev/null | sort -rn
echo ""

# ─── Python complexity ────────────────────────────────────────────
echo "── Python complexity ──"
for f in $(find . -maxdepth 5 -not -path './.git/*' -not -path './.venv/*' -not -path './__pycache__/*' -type f -name '*.py'); do
    funcs=$(grep -c 'def ' "$f" || true)
    lines=$(wc -l < "$f")
    classes=$(grep -c '^class ' "$f" || true)
    if [ "$funcs" -gt 0 ]; then
        avg=$((lines / funcs))
        printf "  %-35s %4d lines | %2d func | %1d class | ~%3d loc/func\n" "$(basename $f)" "$lines" "$funcs" "$classes" "$avg"
    fi
done
echo ""

# ─── Git stats ────────────────────────────────────────────────────
if git rev-parse --git-dir >/dev/null 2>&1; then
    echo "── Git stats ──"
    commits=$(git log --oneline 2>/dev/null | wc -l)
    echo "  Commits: $commits"

    if [ "$commits" -gt 0 ]; then
        echo ""
        echo "── Commit history ──"
        git log --oneline 2>/dev/null
    fi

    # Contributors
    contributors=$(git shortlog -sne 2>/dev/null | wc -l)
    if [ "$contributors" -gt 0 ]; then
        echo ""
        echo "── Top contributors ──"
        git shortlog -sne 2>/dev/null | head -5
    fi

    # Lines added/removed per commit (last 10)
    echo ""
    echo "── Recent changes (lines +/-) ──"
    git log --oneline --stat=5,5 -n 10 2>/dev/null | grep -E '^[a-f0-9]+|\.py$|\.html$|\.css$' || true
fi

# ─── Dependencies (unique imports) ────────────────────────────────
echo ""
echo "── Dependencies (unique imports) ──"
find . -maxdepth 5 -not -path './.git/*' -not -path './.venv/*' -not -path './__pycache__/*' -type f -name '*.py' | xargs grep -h '^import\|^from ' 2>/dev/null | sort -u
echo ""

# ─── Project structure (depth 3) ──────────────────────────────────
echo "── Project structure (depth 3) ──"
find . -maxdepth 3 \
    -not -path './.git/*' \
    -not -path './.venv/*' \
    -type d | sort
