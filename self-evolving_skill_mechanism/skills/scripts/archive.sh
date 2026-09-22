#!/usr/bin/env bash
# 归档本轮草稿，并把 draft.md 重置为空模板
# 用法：bash scripts/archive.sh
set -euo pipefail

cd "$(dirname "$0")/.."
DRAFT="pending/draft.md"
STAMP=$(date +%Y%m)
TARGET="pending/archive-${STAMP}.md"

if [ ! -s "$DRAFT" ]; then
  echo "草稿为空，无需归档"
  exit 0
fi

# 提取有效草稿行（跳过标题、注释、空行、表格）
BODY=$(grep -vE '^\s*(#|<!--|-->|\||>|$)' "$DRAFT" || true)

if [ -z "$BODY" ]; then
  echo "草稿无有效内容，无需归档"
  exit 0
fi

if [ -f "$TARGET" ]; then
  printf '\n## %s\n\n' "$(date '+%F %T')" >> "$TARGET"
else
  printf '# 草稿归档 %s\n\n## %s\n\n' "$STAMP" "$(date '+%F %T')" > "$TARGET"
fi

printf '%s\n' "$BODY" >> "$TARGET"

# 重置为空模板
cat > "$DRAFT" <<'EOF'
# 待整合草稿（会话内累积）

> 一行一条，只求快。不分析、不排版、不打断主任务。
> 整合完毕后由 scripts/archive.sh 归档，本文件重置。

## 本轮草稿

<!-- [信号类型 A-F] 场景 → 正确做法 -->
EOF

echo "已归档 $(printf '%s\n' "$BODY" | wc -l | tr -d ' ') 条 → $TARGET"
