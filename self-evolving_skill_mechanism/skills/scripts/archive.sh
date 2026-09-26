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

# ⛔ FL-05 清单第 1 项「归档前必须先整合」——强制校验
#    ⛔ 清单不会自己执行。实测我自己就跳过一次：先归档后整合，
#       archive.sh 正常退出 0，捕获**永久丢失**。
#    ⇒ 比对 consolidate.py 记录的草稿指纹；不匹配 = 整合后草稿又变了
#      （或压根没整合）→ 拦下并提示。
#    退出码 3 = ENV（前置条件不满足，先去做那一步）。
STAMP="pending/.last_consolidated"
CUR=$(sha1sum "$DRAFT" | cut -c1-16)
if [ ! -f "$STAMP" ]; then
  echo "[blocked] 没有整合记录（$STAMP 不存在）" >&2
  echo "  ⛔ 归档会重置 draft.md —— 没整合就归档 = 本轮捕获永久丢失" >&2
  echo "  → 先跑：python3 scripts/consolidate.py" >&2
  exit 3
fi
LAST=$(cut -d' ' -f1 "$STAMP")
if [ "$CUR" != "$LAST" ]; then
  echo "[blocked] 草稿在整合之后又变过（整合时 $LAST / 现在 $CUR）" >&2
  echo "  ⛔ 归档会重置 draft.md —— 未整合的捕获永久丢失" >&2
  echo "  → 先跑：python3 scripts/consolidate.py" >&2
  exit 3
fi

# 提取有效草稿行（跳过标题、注释、空行）
# ⚠ 早先的正则把 `|` 开头的行也过滤了（想跳过表格分隔线），
#   但**表格形式写的捕获会被整条静默丢弃**——
#   实测：草稿里 1 条表格 + 1 条列表，只归档了列表那条，退出码 0、无警告。
#   而归档后 draft.md 会被重置 → **内容永久丢失**。
#   这是典型的「静默少做」：不报错、不为空，只是少了一半。
# ⛔ 第一版把 `<!--` 一律当注释丢弃，而 draft 模板**规定的捕获格式就是**
#    `<!-- [A] 场景 → 正确做法 -->`
#    ⇒ 按模板写的捕获 **100% 被静默丢弃**，而 draft 随后被重置 → **永久丢失**。
#    实测（主链路第一次真跑）：写了 6 条，归档 2 条，6 条全没了。
#    这是典型的「静默少做」：不报错、不为空，只是少了一半。
#
# 捕获注释（以 `<!-- [` 开头）= **内容**，必须保留。
# 装饰性注释才是注释。
BODY=$(awk '
  /^[ \t]*#/   { next }
  /^[ \t]*>/   { next }
  /^[ \t]*-->/ { next }
  /^[ \t]*$/   { next }
  /^[ \t]*<!--[ \t]*\[[A-G][0-9]?\]/ { print; next }
  /^[ \t]*<!--/ { next }
  { print }
' "$DRAFT")
# ⚠ 基线必须在**任何过滤之前**数：
#    第一版 RAW_COUNT 与 BODY 用的是**同一个过滤器**，
#    ⇒ 两者恒等，告警永远不响 —— 守卫从构造上就不可能发现丢数据。
RAW_COUNT=$(awk '
  /^[ \t]*#/   { next }
  /^[ \t]*>/   { next }
  /^[ \t]*$/   { next }
  /^[ \t]*<!--[ \t]*\[/ { next }
  { c++ }
  END { print c+0 }
' "$DRAFT")

if [ -z "$BODY" ]; then
  echo "草稿无有效内容，无需归档"
  exit 0
fi

# 表格形式现在保留；只跳过纯分隔线（| --- | --- |）
BODY=$(printf '%s\n' "$BODY" | grep -vE '^\s*\|[\s:|-]+\|\s*$' || true)

KEPT=$(printf '%s\n' "$BODY" | grep -cvE '^\s*$' || true)
if [ "$KEPT" -lt "$RAW_COUNT" ]; then
  echo "[warn] 草稿 $RAW_COUNT 行 → 归档 $KEPT 行（少了 $((RAW_COUNT - KEPT)) 行）" >&2
  echo "[warn] 若是表格分隔线属正常；若是你写的捕获被丢，请看脚本里的过滤规则" >&2
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
