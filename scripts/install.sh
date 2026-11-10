#!/usr/bin/env bash
# 安装 labor-law-cn 到本机 agent 技能目录。
#
#   bash scripts/install.sh                 # 安装到 ~/.claude/skills/labor-law-cn
#   bash scripts/install.sh /path/to/skills # 安装到指定 skills 目录下的 labor-law-cn
#   bash scripts/install.sh --force ...     # 覆盖已存在的同名技能
#
# 安装后 agent 读取 SKILL.md 即可使用；所有命令在技能根目录执行。
set -euo pipefail

FORCE=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) ARGS+=("$arg") ;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="${ARGS[0]:-$HOME/.claude/skills}"
TARGET="$SKILLS_DIR/labor-law-cn"

echo "源目录 : $SRC"
echo "目标   : $TARGET"

if [ ! -f "$SRC/SKILL.md" ] || [ ! -f "$SRC/data/index.json" ]; then
  echo "错误：$SRC 不是完整的 labor-law-cn 项目（缺 SKILL.md 或 data/index.json）" >&2
  exit 1
fi

command -v python3 >/dev/null || { echo "错误：需要 python3" >&2; exit 1; }
python3 -c "import yaml" 2>/dev/null || { echo "提示：建议安装 PyYAML（pip install pyyaml）" >&2; }

mkdir -p "$SKILLS_DIR"
if [ -e "$TARGET" ]; then
  if [ "$FORCE" -ne 1 ]; then
    echo "目标已存在：$TARGET" >&2
    echo "如需覆盖请加 --force（会先备份为 $TARGET.bak-$(date +%Y%m%d%H%M%S)）" >&2
    exit 1
  fi
  BACKUP="$TARGET.bak-$(date +%Y%m%d%H%M%S)"
  mv "$TARGET" "$BACKUP"
  echo "已备份旧版本到 $BACKUP"
fi

# 只复制运行所需内容，跳过抓取缓存与 .git
mkdir -p "$TARGET"
for item in SKILL.md SCHEMA.md README.md LICENSE LICENSE-CODE data docs templates examples scripts tests; do
  [ -e "$SRC/$item" ] || continue
  cp -R "$SRC/$item" "$TARGET/"
done
find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$TARGET/data/manifest.json" 2>/dev/null || true

python3 "$TARGET/scripts/build_index.py" >/dev/null
python3 "$TARGET/scripts/verify.py" >/dev/null

echo
echo "✅ 安装完成：$TARGET"
echo "   文档数：$(python3 "$TARGET/scripts/search.py" --stats | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])')"
echo
echo "使用示例："
echo "  cd $TARGET"
echo "  python3 scripts/search.py 加班费 --status 有效"
echo "  python3 scripts/search.py --doc 劳动合同法 --article 82"
echo "  python3 scripts/search.py --age 超龄"
echo
echo "在 Claude Code / DSH 中，技能通常在下次会话或技能重新扫描后可用。"
