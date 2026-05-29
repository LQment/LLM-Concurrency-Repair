#!/bin/bash
# ============================================================
# parallel_run.sh — 并发运行 CHATREPAIR 修复多个 bug
#
# 用法:
#   bash scripts/parallel_run.sh <mode> <project> <y/n> [bug_numbers] [parallel_limit]
#
# 参数:
#   mode           : chatrepair | agentrepair | initial-chat | initial-save
#   project        : Lang | Chart | Closure | Math | Mockito | Time
#   y/n            : y=single-function, n=single-line/hunk
#   bug_numbers    : 空格分隔的 bug 编号，如 "1 10 12 14"（默认自动从 patches/ 目录读取）
#   parallel_limit : 最大并发数（默认 2，避免 API 限流）
#
# 示例:
#   bash scripts/parallel_run.sh chatrepair Lang y "10 12 14" 2
#   bash scripts/parallel_run.sh agentrepair Lang y "14 51" 2
#   bash scripts/parallel_run.sh chatrepair Lang y                 # 自动运行所有 Lang bug
#   bash scripts/parallel_run.sh chatrepair Chart y "1 2 3" 3
# ============================================================

MODE="${1:-chatrepair}"
PROJECT="${2:-Lang}"
SINGLE_FUNC="${3:-y}"
BUG_NUMBERS="${4}"
MAX_PARALLEL="${5:-2}"

# 项目根目录 = scripts/ 的父目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 如果未指定 bug 列表，从 patches/ 目录自动读取
if [ -z "$BUG_NUMBERS" ]; then
    PATCH_DIR="$PROJECT_ROOT/patches/$PROJECT"
    if [ ! -d "$PATCH_DIR" ]; then
        echo "ERROR: patches directory not found: $PATCH_DIR"
        exit 1
    fi
    BUG_NUMBERS=$(ls "$PATCH_DIR"/*.json 2>/dev/null | xargs -n1 basename | sed 's/\.json$//' | sort -n | tr '\n' ' ')
    if [ -z "$BUG_NUMBERS" ]; then
        echo "ERROR: No patch files found in $PATCH_DIR"
        exit 1
    fi
fi

# 自动检测 Python 解释器（必须能 import openai）
PYTHON=""
# 方式1：用 python 命令（venv 中的优先）
for py in python python3; do
    p=$(command -v "$py" 2>/dev/null)
    if [ -n "$p" ] && [ -x "$p" ] && "$p" -c "import openai" 2>/dev/null; then
        PYTHON="$p"
        break
    fi
done
# 方式2：用已知的 Windows Python 绝对路径
if [ -z "$PYTHON" ]; then
    for py in /c/Python313/python /c/Python312/python /c/Python311/python; do
        if [ -x "$py" ] && "$py" -c "import openai" 2>/dev/null; then
            PYTHON="$py"
            break
        fi
    done
fi
if [ -z "$PYTHON" ]; then
    echo "ERROR: No Python found with openai module installed!"
    echo "Checked: python, python3, /c/Python31*/python"
    echo "Install: pip install openai"
    exit 1
fi

echo "============================================"
echo "  CHATREPAIR Parallel Runner"
echo "============================================"
echo "  Mode:       $MODE"
echo "  Project:    $PROJECT"
echo "  Single-func: $SINGLE_FUNC"
echo "  Bugs:       $BUG_NUMBERS"
echo "  Parallel:   $MAX_PARALLEL"
echo "  Python:     $PYTHON ($($PYTHON --version 2>&1))"
echo "============================================"

# 创建日志目录
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
RUN_ID="$(date '+%Y%m%d_%H%M%S')"
SUMMARY_FILE="$LOG_DIR/summary_${PROJECT}_${RUN_ID}.log"
RUN_TIMEOUT_S="${CHATREPAIR_RUN_TIMEOUT_S:-0}"
: > "$SUMMARY_FILE"
: > "$LOG_DIR/summary.log"

RUNNING=0
TOTAL=0
SUCCESS=0
FAIL=0

for BUG in $BUG_NUMBERS; do
    TOTAL=$((TOTAL + 1))
done

echo ""
echo "[$(date '+%H:%M:%S')] Starting $TOTAL bugs, max $MAX_PARALLEL in parallel..."
echo ""

for BUG in $BUG_NUMBERS; do
    # 等待直到有空闲槽位
    while [ $RUNNING -ge $MAX_PARALLEL ]; do
        wait -n 2>/dev/null
        RUNNING=$((RUNNING - 1))
    done

    LOG_FILE="$LOG_DIR/${PROJECT}_bug${BUG}_$(date '+%Y%m%d_%H%M%S').log"

    echo "[$(date '+%H:%M:%S')] Launching $PROJECT-$BUG (log: $LOG_FILE)"

    (
        cd "$PROJECT_ROOT"
        if [ "$RUN_TIMEOUT_S" -gt 0 ]; then
            timeout "$RUN_TIMEOUT_S" "$PYTHON" -u src/main.py "$MODE" "$PROJECT" "$SINGLE_FUNC" "$BUG" > "$LOG_FILE" 2>&1
        else
            "$PYTHON" -u src/main.py "$MODE" "$PROJECT" "$SINGLE_FUNC" "$BUG" > "$LOG_FILE" 2>&1
        fi
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 124 ]; then
            STATUS_LINE="[$(date '+%H:%M:%S')] $PROJECT-$BUG: TIMEOUT (exit=$EXIT_CODE)"
        elif [ $EXIT_CODE -ne 0 ]; then
            STATUS_LINE="[$(date '+%H:%M:%S')] $PROJECT-$BUG: FAILED (exit=$EXIT_CODE)"
        elif grep -q "AgentRepair PASS" "$LOG_FILE"; then
            STATUS_LINE="[$(date '+%H:%M:%S')] $PROJECT-$BUG: PASS"
        elif grep -q "AgentRepair FAIL" "$LOG_FILE"; then
            STATUS_LINE="[$(date '+%H:%M:%S')] $PROJECT-$BUG: FAIL"
        elif grep -q "Skipped (empty prompt)" "$LOG_FILE"; then
            STATUS_LINE="[$(date '+%H:%M:%S')] $PROJECT-$BUG: SKIPPED"
        else
            STATUS_LINE="[$(date '+%H:%M:%S')] $PROJECT-$BUG: DONE (exit=$EXIT_CODE)"
        fi
        echo "$STATUS_LINE" >> "$SUMMARY_FILE"
        cp "$SUMMARY_FILE" "$LOG_DIR/summary.log"
    ) &

    RUNNING=$((RUNNING + 1))
done

# 等待所有后台任务完成
wait

echo ""
echo "============================================"
echo "  All bugs completed!"
echo "  Logs: $LOG_DIR/"
echo "  Summary: $SUMMARY_FILE"
echo "============================================"
cat "$SUMMARY_FILE" 2>/dev/null
