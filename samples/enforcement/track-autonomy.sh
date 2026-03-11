#!/bin/bash
# V11 Hook: track-autonomy (PostToolUse — Write|Edit|Bash)
# Updates trust metrics AND writes audit log in a single pass.
# Replaces V8 track-autonomy-score (193L) + audit-autonomy-action (191L).
# Never blocks (exit 0 always).
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

# --- CLI flags ---
if [ "$1" == "--test" ]; then echo "track-autonomy v1 (merged score+audit)"; exit 0; fi

if [ "$1" == "--recent" ]; then
    AUDIT_LOG="$METRICS_DIR/autonomy-audit.jsonl"
    if [ -f "$AUDIT_LOG" ]; then tail -n "${2:-20}" "$AUDIT_LOG" | jq -s '.'; else echo "[]"; fi
    exit 0
fi

if [ "$1" == "--stats" ]; then
    AUDIT_LOG="$METRICS_DIR/autonomy-audit.jsonl"
    if [ -f "$AUDIT_LOG" ]; then
        echo "=== Autonomy Audit Statistics ==="
        echo "Total entries: $(wc -l < "$AUDIT_LOG")"
        echo ""; echo "By outcome:"
        jq -s 'group_by(.outcome) | map({outcome: .[0].outcome, count: length})' "$AUDIT_LOG"
        echo ""; echo "By risk level:"
        jq -s 'group_by(.risk_level) | map({risk_level: .[0].risk_level, count: length})' "$AUDIT_LOG"
        echo ""; echo "By approval method:"
        jq -s 'group_by(.approval_method) | map({method: .[0].approval_method, count: length})' "$AUDIT_LOG"
    else echo "No audit log found"; fi
    exit 0
fi

# --- Main hook logic ---
v11_parse_input
case "$V11_TOOL_NAME" in Write|Edit|Bash) ;; *) exit 0 ;; esac

RISK_LEVEL=$(v11_risk_level)
[ "$RISK_LEVEL" == "low" ] && exit 0

mkdir -p "$METRICS_DIR"

# Outcome
OUTCOME="success"
[ -n "$V11_ERROR" ] && [ "$V11_ERROR" != "null" ] && OUTCOME="error"

# Category from file extension or command
CATEGORY="other"
if [ -n "$V11_FILE_PATH" ]; then
    case "${V11_FILE_PATH##*.}" in
        ts|tsx|js|jsx) CATEGORY="typescript" ;;
        py)            CATEGORY="python" ;;
        sh|bash)       CATEGORY="shell" ;;
        md)            CATEGORY="markdown" ;;
        json|yaml|yml) CATEGORY="config" ;;
    esac
elif [ -n "$V11_COMMAND" ]; then
    case "$V11_COMMAND" in
        git\ *)                  CATEGORY="git" ;;
        docker\ *)               CATEGORY="docker" ;;
        npm\ *|yarn\ *|pnpm\ *) CATEGORY="npm" ;;
        *)                       CATEGORY="shell" ;;
    esac
fi

NOW=$(date -Iseconds)

# Detect project from file path or command (moved before state file determination)
v11_detect_project "$V11_FILE_PATH"
if [ -z "$V11_PROJECT" ] && [ -n "$V11_COMMAND" ]; then
    CMD_PATH=$(printf '%s' "$V11_COMMAND" | grep -oE "$HERCULES_ROOT/[^ ]+" | head -1)
    [ -n "$CMD_PATH" ] && v11_detect_project "$CMD_PATH"
fi

# Write to project-local state if project detected, else NOOP (don't track)
if [ -n "$V11_PROJECT" ]; then
    STATE_FILE="$SESSIONS_ROOT/$V11_PROJECT/.autonomy-state"
    mkdir -p "$(dirname "$STATE_FILE")"
else
    # No project context — skip state update (safety fallback)
    STATE_FILE=""
fi

# ==== PART A: Update Trust Score ====

if [ -n "$STATE_FILE" ] && [ -f "$STATE_FILE" ]; then
    STATE=$(cat "$STATE_FILE")
else
    STATE=$(jq -n --arg t "$NOW" '{
        level:0, successful:0, errors:0, rollbacks:0,
        approved_categories:[], grants:[],
        high_risk_history:[], recent_errors:[], last_updated:$t}')
fi

CURRENT_LEVEL=$(printf '%s' "$STATE" | jq -r '.level // 0')
SUCCESSFUL=$(printf '%s' "$STATE" | jq -r '.successful // 0')
ERRORS=$(printf '%s' "$STATE" | jq -r '.errors // 0')
ROLLBACKS=$(printf '%s' "$STATE" | jq -r '.rollbacks // 0')

if [ "$OUTCOME" == "success" ]; then
    SUCCESSFUL=$((SUCCESSFUL + 1))
    # Add category to approved_categories if not present
    if [ -n "$CATEGORY" ] && [ "$CATEGORY" != "other" ]; then
        STATE=$(printf '%s' "$STATE" | jq --arg c "$CATEGORY" \
            'if (.approved_categories | index($c)) then . else .approved_categories += [$c] end')
    fi
    # Escalation thresholds (A3→A4 requires explicit user grant)
    NEW_LEVEL=$CURRENT_LEVEL
    if   [ "$CURRENT_LEVEL" -eq 0 ] && [ "$SUCCESSFUL" -ge 5 ]; then NEW_LEVEL=1
    elif [ "$CURRENT_LEVEL" -eq 1 ] && [ "$SUCCESSFUL" -ge 10 ] && [ "$ROLLBACKS" -eq 0 ]; then NEW_LEVEL=2
    elif [ "$CURRENT_LEVEL" -eq 2 ] && [ "$SUCCESSFUL" -ge 25 ]; then NEW_LEVEL=3; fi
    if [ "$NEW_LEVEL" -gt "$CURRENT_LEVEL" ]; then
        CURRENT_LEVEL=$NEW_LEVEL
        echo "[$NOW] Autonomy escalated to A$CURRENT_LEVEL (successful=$SUCCESSFUL)" \
            >> "$METRICS_DIR/autonomy-changes.log"
    fi
else
    ERRORS=$((ERRORS + 1))
    # Record in recent_errors (keep last 10)
    STATE=$(printf '%s' "$STATE" | jq --arg t "$NOW" --arg e "${V11_ERROR:0:200}" \
        '.recent_errors = ([{timestamp:$t, error:$e}] + .recent_errors)[:10]')
    if [ "$CURRENT_LEVEL" -gt 0 ]; then
        NEW_LEVEL=$((CURRENT_LEVEL - 1))
        # 2+ errors in 10 min → drop to A0
        RECENT_COUNT=$(printf '%s' "$STATE" | jq \
            '[.recent_errors[] | select(.timestamp > (now - 600 | todate))] | length' 2>/dev/null)
        [ "${RECENT_COUNT:-0}" -ge 2 ] && NEW_LEVEL=0
        CURRENT_LEVEL=$NEW_LEVEL
        echo "[$NOW] Autonomy de-escalated to A$CURRENT_LEVEL (errors=$ERRORS)" \
            >> "$METRICS_DIR/autonomy-changes.log"
    fi
fi

# Persist updated state (only if project-local) — flock prevents race under parallel teammates
if [ -n "$STATE_FILE" ]; then
    (
        flock -w 5 200 || exit 0
        printf '%s' "$STATE" | jq \
            --argjson level "$CURRENT_LEVEL" --argjson successful "$SUCCESSFUL" \
            --argjson errors "$ERRORS" --argjson rollbacks "$ROLLBACKS" --arg t "$NOW" \
            '.level=$level|.successful=$successful|.errors=$errors|.rollbacks=$rollbacks|.last_updated=$t' \
            > "$STATE_FILE"
    ) 200>"$STATE_FILE.lock"
fi

# ==== PART B: Write Audit Entry ====

# Approval method based on autonomy level
APPROVAL_METHOD="explicit"; GRANT_MATCHED=""
case "$CURRENT_LEVEL" in
    1) APPROVAL_METHOD="category_repeat" ;;
    2) # Check grants for matching file pattern
       if [ -n "$V11_FILE_PATH" ]; then
           while IFS= read -r grant; do
               [ -z "$grant" ] || [ "$grant" == "null" ] && continue
               PATTERN=$(printf '%s' "$grant" | jq -r '.pattern // empty')
               [ -z "$PATTERN" ] && continue
               # shellcheck disable=SC2053
               if [[ "$V11_FILE_PATH" == $PATTERN ]]; then
                   APPROVAL_METHOD="grant_scope"; GRANT_MATCHED="$PATTERN"; break
               fi
           done < <(printf '%s' "$STATE" | jq -c '.grants // [] | .[]' 2>/dev/null)
       fi
       [ -z "$GRANT_MATCHED" ] && APPROVAL_METHOD="explicit" ;;
    3) APPROVAL_METHOD="trusted_medium" ;;
    4) APPROVAL_METHOD="autonomous" ;;
esac

# === V11.4: Enriched audit fields ===

# Task ID from active task state
AUDIT_TASK_ID=""
if [ -n "$V11_PROJECT" ]; then
    TASK_STATE_F="$TASK_STATE_DIR/${V11_PROJECT}.json"
    if [ -f "$TASK_STATE_F" ]; then
        AUDIT_TASK_ID=$(jq -r '(.active_task_ids // [])[0] // ""' "$TASK_STATE_F" 2>/dev/null)
    fi
fi

# Agent ID from environment
AUDIT_AGENT_ID="${V11_AGENT_ID:-}"

# Diff summary and hash for git-tracked files
AUDIT_DIFF_SUMMARY=""
AUDIT_DIFF_HASH=""
AUDIT_FILE="${V11_FILE_PATH:-$V11_COMMAND}"
if [ -n "$V11_FILE_PATH" ] && [ -f "$V11_FILE_PATH" ]; then
    FILE_DIR=$(dirname "$V11_FILE_PATH")
    if [ -d "$FILE_DIR/.git" ] || git -C "$FILE_DIR" rev-parse --git-dir &>/dev/null; then
        AUDIT_DIFF_SUMMARY=$(cd "$FILE_DIR" && git diff --stat -- "$(basename "$V11_FILE_PATH")" 2>/dev/null | tail -1 || echo "")
        AUDIT_DIFF_HASH=$(cd "$FILE_DIR" && git diff -- "$(basename "$V11_FILE_PATH")" 2>/dev/null | md5sum 2>/dev/null | cut -c1-8 || echo "")
    fi
fi

# V11.4: Full diff storage (opt-in per project)
if [ -n "$V11_PROJECT" ] && [ -n "$AUDIT_DIFF_HASH" ] && [ "$AUDIT_DIFF_HASH" != "d41d8cd9" ]; then
    AUDIT_CONFIG="$SESSIONS_ROOT/$V11_PROJECT/.audit-config.json"
    if [ -f "$AUDIT_CONFIG" ]; then
        CAPTURE_DIFFS=$(jq -r '.capture_diffs // false' "$AUDIT_CONFIG" 2>/dev/null)
        MAX_DIFF_KB=$(jq -r '.max_diff_size_kb // 50' "$AUDIT_CONFIG" 2>/dev/null)
        if [ "$CAPTURE_DIFFS" = "true" ] && [ -n "$V11_FILE_PATH" ]; then
            DIFF_DIR="$SESSIONS_ROOT/$V11_PROJECT/audit-diffs"
            mkdir -p "$DIFF_DIR"
            DIFF_CONTENT=$(cd "$(dirname "$V11_FILE_PATH")" && git diff -- "$(basename "$V11_FILE_PATH")" 2>/dev/null || echo "")
            DIFF_SIZE=$(printf '%s' "$DIFF_CONTENT" | wc -c)
            MAX_BYTES=$((MAX_DIFF_KB * 1024))
            if [ "$DIFF_SIZE" -gt 0 ] && [ "$DIFF_SIZE" -le "$MAX_BYTES" ]; then
                PATCH_FILE="$DIFF_DIR/$(date +%Y%m%d-%H%M%S)-${AUDIT_DIFF_HASH}.patch"
                printf '%s\n' "$DIFF_CONTENT" > "$PATCH_FILE"
            fi
        fi
    fi
fi

# Append JSONL audit entry (V11.4: enriched with task_id, agent_id, diff fields)
AUDIT_LOG="$METRICS_DIR/autonomy-audit.jsonl"
jq -nc \
    --arg ts "$NOW" --arg sid "${V11_SESSION_ID:-unknown}" \
    --arg proj "${V11_PROJECT:-}" --arg action "$V11_TOOL_NAME" \
    --arg file "$AUDIT_FILE" --arg risk "$RISK_LEVEL" \
    --argjson alevel "$CURRENT_LEVEL" --arg method "$APPROVAL_METHOD" \
    --arg grant "$GRANT_MATCHED" --arg outcome "$OUTCOME" \
    --arg err "${V11_ERROR:-}" \
    --arg task_id "$AUDIT_TASK_ID" --arg agent_id "$AUDIT_AGENT_ID" \
    --arg diff_summary "$AUDIT_DIFF_SUMMARY" --arg diff_hash "$AUDIT_DIFF_HASH" \
    '{timestamp:$ts, session_id:$sid,
      project:(if $proj=="" then null else $proj end),
      action:$action, file:$file, risk_level:$risk,
      autonomy_level:$alevel, approval_method:$method,
      grant_matched:(if $grant=="" then null else $grant end),
      outcome:$outcome,
      error:(if $err=="" then null else $err end),
      task_id:(if $task_id=="" then null else $task_id end),
      agent_id:(if $agent_id=="" then null else $agent_id end),
      diff_summary:(if $diff_summary=="" then null else $diff_summary end),
      diff_hash:(if $diff_hash=="" then null else $diff_hash end)}' >> "$AUDIT_LOG"

# Rotate if >10MB: archive old entries, keep last 50000
if [ -f "$AUDIT_LOG" ]; then
    LOG_SIZE=$(stat -c%s "$AUDIT_LOG" 2>/dev/null || echo 0)
    if [ "$LOG_SIZE" -gt 10485760 ]; then
        head -n -50000 "$AUDIT_LOG" | gzip > "$METRICS_DIR/autonomy-audit.$(date +%Y%m%d-%H%M%S).jsonl.gz"
        tail -n 50000 "$AUDIT_LOG" > "$AUDIT_LOG.tmp"
        mv "$AUDIT_LOG.tmp" "$AUDIT_LOG"
    fi
fi

exit 0
