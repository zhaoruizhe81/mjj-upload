#!/usr/bin/env bash
#
# 整个目录批量上传，生成 Markdown 图集
#
#   ./examples/batch-markdown.sh ./shots album.md
#
set -euo pipefail

MJJ="${MJJ:-mjj}"
DIR="${1:-.}"
OUT="${2:-album.md}"

shopt -s nullglob nocaseglob
files=("$DIR"/*.png "$DIR"/*.jpg "$DIR"/*.jpeg "$DIR"/*.gif "$DIR"/*.webp)
shopt -u nullglob nocaseglob

if [ "${#files[@]}" -eq 0 ]; then
  echo "在 $DIR 里没找到图片" >&2
  exit 1
fi

echo "共 ${#files[@]} 张，开始上传（并发 5）…" >&2
"$MJJ" -q -j 5 -f markdown -o "$OUT" "${files[@]}" > /dev/null

echo "已写入 $OUT：" >&2
head -5 "$OUT" >&2
[ "${#files[@]}" -gt 5 ] && echo "…（共 $(wc -l < "$OUT" | tr -d ' ') 行）" >&2
