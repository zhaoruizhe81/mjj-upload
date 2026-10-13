#!/usr/bin/env bash
#
# 截图 → 直链 → 剪贴板（macOS）
#
#   ./examples/screenshot-to-url.sh          交互式框选截图
#   ./examples/screenshot-to-url.sh full     全屏截图
#
# 依赖：macOS 自带 screencapture / pbcopy；mjj 在 PATH 里
#       （没装的话把下面 MJJ 换成 python3 /path/to/mjj_upload.py）
#
set -euo pipefail

MJJ="${MJJ:-mjj}"
MODE="${1:-select}"
TMP="$(mktemp -t mjj-shot).png"

case "$MODE" in
  full) screencapture -x "$TMP" ;;      # -x 不播放快门声
  *)    screencapture -i -x "$TMP" ;;   # -i 交互框选，按 ESC 取消
esac

# 用户按 ESC 取消时 screencapture 不会生成文件
if [ ! -s "$TMP" ]; then
  echo "已取消（没有截图）" >&2
  exit 1
fi

URL="$("$MJJ" "$TMP")"
rm -f "$TMP"

printf '%s' "$URL" | pbcopy
echo "$URL"
echo "（已复制到剪贴板）" >&2
