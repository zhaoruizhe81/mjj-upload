#!/usr/bin/env bash
#
# 把 mjj-upload 安装成 dsh / Claude 技能（默认装到 ~/.dsh/skills/mjj-image-host）
#
#   ./skill/install.sh                 # 复制安装（默认，自带一份脚本副本）
#   ./skill/install.sh --link          # 软链安装（指向仓库里的脚本，改完即时生效）
#   ./skill/install.sh --dest DIR      # 换安装根目录
#   ./skill/install.sh --uninstall     # 卸载
#   ./skill/install.sh --help
#
set -euo pipefail

SKILL_NAME="mjj-image-host"
REPO_URL="https://github.com/zhaoruizhe81/mjj-upload"
MODE="copy"
DO_UNINSTALL=0
DEST_ROOT="${DSH_SKILLS_DIR:-${DSH_HOME:-$HOME/.dsh}/skills}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_SKILL_MD="$REPO_ROOT/skill/SKILL.md"
SRC_PROTOCOL="$REPO_ROOT/skill/references/protocol.md"
SRC_SCRIPT="$REPO_ROOT/mjj_upload.py"

usage() {
  sed -n '3,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<EOF

当前解析到的安装根目录: $DEST_ROOT
  （优先级: --dest > \$DSH_SKILLS_DIR > \$DSH_HOME/skills > ~/.dsh/skills）
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --link)      MODE="link" ;;
    --copy)      MODE="copy" ;;
    --uninstall) DO_UNINSTALL=1 ;;
    --dest)      DEST_ROOT="${2:?--dest 需要一个目录参数}"; shift ;;
    --dest=*)    DEST_ROOT="${1#*=}" ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "未知参数: $1（--help 看用法）" >&2; exit 2 ;;
  esac
  shift
done

TARGET="$DEST_ROOT/$SKILL_NAME"

if [ "$DO_UNINSTALL" = "1" ]; then
  # 只删 SKILL_NAME 这一层，且必须确认路径形态正常
  case "$TARGET" in
    */"$SKILL_NAME") ;;
    *) echo "拒绝操作: 目标路径异常 -> $TARGET" >&2; exit 1 ;;
  esac
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    rm -rf "$TARGET"
    echo "已卸载: $TARGET"
  else
    echo "未安装: $TARGET"
  fi
  exit 0
fi

for f in "$SRC_SKILL_MD" "$SRC_PROTOCOL" "$SRC_SCRIPT"; do
  [ -f "$f" ] || { echo "缺少文件: $f（请在仓库目录里运行本脚本）" >&2; exit 1; }
done

mkdir -p "$TARGET/scripts" "$TARGET/references"
cp "$SRC_SKILL_MD"  "$TARGET/SKILL.md"
cp "$SRC_PROTOCOL"  "$TARGET/references/protocol.md"

if [ "$MODE" = "link" ]; then
  ln -sf "$SRC_SCRIPT" "$TARGET/scripts/mjj_upload.py"
  echo "脚本以软链方式安装 -> $SRC_SCRIPT"
else
  rm -f "$TARGET/scripts/mjj_upload.py"
  cp "$SRC_SCRIPT" "$TARGET/scripts/mjj_upload.py"
fi
chmod 755 "$TARGET" "$TARGET/scripts" "$TARGET/references" "$TARGET/scripts/mjj_upload.py"
chmod 644 "$TARGET/SKILL.md" "$TARGET/references/protocol.md"

cat > "$TARGET/_source.txt" <<EOF
source: 本地自制（逆向 https://mjj.today/ 前端上传器）
upstream: $REPO_URL
repo:   $REPO_ROOT
date:   $(date -u +%Y-%m-%dT%H:%M:%SZ)
mode:   $MODE
EOF

echo
echo "✅ 已安装: $TARGET"
echo "   验证: python3 \"$TARGET/scripts/mjj_upload.py\" --help"
echo
echo "想在任何目录直接敲 \`mjj\`："
echo "   mkdir -p ~/.local/bin && ln -sf \"$SRC_SCRIPT\" ~/.local/bin/mjj"
echo "   （确认 ~/.local/bin 在 \$PATH 里）"
