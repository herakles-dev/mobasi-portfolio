#!/bin/bash
# V11 Hook: guard-write-gates (PreToolUse — Write|Edit)
# Consolidated write requirements: combines guard-task-state + guard-plan-mode.
# Enforces task-state requirement and provides plan mode guidance.
#
# Performance: 2 hooks → 1 hook (reduces PreToolUse overhead by ~50ms)
#
# Exit codes:
#   0 - Allow operation (may include advisory warning)
#   2 - Block operation (task-state violation only; plan-mode is advisory)

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

V11_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRACKING_FILE="$METRICS_DIR/plan-mode-tracking.json"

# Test mode
if [ "$1" == "--test" ]; then
    echo "guard-write-gates v1 (consolidated: task-state + plan-mode)"
    exit 0
fi

# Reset tracking state
if [ "$1" == "--reset" ]; then
    rm -f "$TRACKING_FILE"
    echo "Plan mode tracking reset."
    exit 0
fi

# Parse hook input
v11_parse_input

# Only guard Write and Edit tools
[ "$V11_TOOL_NAME" != "Write" ] && [ "$V11_TOOL_NAME" != "Edit" ] && exit 0

# No file path means nothing to guard
[ -z "$V11_FILE_PATH" ] && exit 0

# Skip metadata and infrastructure files
v11_is_metadata_file "$V11_FILE_PATH" && exit 0

# Skip hook development paths
[[ "$V11_FILE_PATH" == */v10/hooks/* || "$V11_FILE_PATH" == */v11/hooks/* ]] && exit 0

# === FILE OWNERSHIP CHECK (Agent Teams only) ===
# Prevents concurrent writes to the same file by different teammates.
# Only active when .formation-registry.json exists in current directory.

if [ -f ".formation-registry.json" ]; then
    # Check if agent ID is set
    if [ -z "${V11_AGENT_ID:-}" ]; then
        cat >&2 <<EOF
AGENT IDENTITY ERROR: V11_AGENT_ID not set in environment

Teammates must be spawned with V11_AGENT_ID set to prevent collisions.

Fix: Team lead should set environment before spawning:
  export V11_AGENT_ID="a123456"
  # ... then invoke teammate agent
EOF
        exit 2
    fi

    # Check file ownership against registry
    if ! v11_check_file_ownership "$V11_FILE_PATH"; then
        # Conflict detected - exit code 1 from v11_check_file_ownership
        exit 2
    fi
fi

# === V11: SCHEMA VALIDATION (Advisory) ===
# Validate formation-registry.json when writing to it
if [[ "$V11_FILE_PATH" == */.formation-registry.json ]] || [[ "$V11_FILE_PATH" == *formation-registry.json ]]; then
    NEW_CONTENT=$(printf '%s' "$V11_RAW_INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null)
    if [ -n "$NEW_CONTENT" ] && [ "$NEW_CONTENT" != "null" ]; then
        REGISTRY_WARN=$(mktemp /tmp/v11-schema-XXXXXX.txt)
        if ! v11_validate_json "$NEW_CONTENT" "formation-registry.schema.json" 2>"$REGISTRY_WARN"; then
            echo "ADVISORY: Formation registry validation warning:" >&2
            cat "$REGISTRY_WARN" >&2
            # Advisory only — don't block
        fi
        rm -f "$REGISTRY_WARN"
    fi
fi

# Validate autonomy state when writing to it
if [[ "$V11_FILE_PATH" == */.autonomy-state ]]; then
    NEW_CONTENT=$(printf '%s' "$V11_RAW_INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null)
    if [ -n "$NEW_CONTENT" ] && [ "$NEW_CONTENT" != "null" ]; then
        AUTONOMY_WARN=$(mktemp /tmp/v11-schema-XXXXXX.txt)
        if ! v11_validate_json "$NEW_CONTENT" "autonomy-state.schema.json" 2>"$AUTONOMY_WARN"; then
            echo "ADVISORY: Autonomy state validation warning:" >&2
            cat "$AUTONOMY_WARN" >&2
        fi
        rm -f "$AUTONOMY_WARN"
    fi
fi

# === TASK STATE CHECK ===

# Detect project
v11_detect_project "$V11_FILE_PATH"

# Fallback 1: Walk up directory tree looking for .task-state.json
if [ -z "$V11_PROJECT" ]; then
    DIR=$(dirname "$V11_FILE_PATH")
    while [ "$DIR" != "/" ] && [ "$DIR" != "$HERCULES_ROOT" ] && [ ${#DIR} -gt ${#HERCULES_ROOT} ]; do
        if [ -f "$DIR/.task-state.json" ]; then
            V11_PROJECT=$(basename "$DIR")
            V11_DETECTION_METHOD="walk-up .task-state.json"
            break
        fi
        DIR=$(dirname "$DIR")
    done
fi

# Fallback 2: Registry lookup for unusual project layouts
if [ -z "$V11_PROJECT" ] && [ -f "$REGISTRY_FILE" ]; then
    V11_PROJECT=$(jq -r --arg path "$V11_FILE_PATH" '
        to_entries
        | map(select(.key[0:1] != "_"))
        | map(select(.value[] as $p | $path | startswith($p)))
        | sort_by(- (.value | map(length) | max))
        | .[0].key // ""
    ' "$REGISTRY_FILE" 2>/dev/null)
    [ "$V11_PROJECT" = "null" ] && V11_PROJECT=""
    [ -n "$V11_PROJECT" ] && V11_DETECTION_METHOD="registry lookup"
fi

# If project detected, check task state
if [ -n "$V11_PROJECT" ]; then
    # Record active project for downstream hooks
    mkdir -p "$(dirname "$ACTIVE_PROJECT_FILE")"
    printf '%s\n' "$V11_PROJECT" > "$ACTIVE_PROJECT_FILE"

    # Check task state
    TASK_STATE=""
    if [ -f "$TASK_STATE_DIR/${V11_PROJECT}.json" ]; then
        TASK_STATE="$TASK_STATE_DIR/${V11_PROJECT}.json"
    elif [ -f "$SESSIONS_ROOT/$V11_PROJECT/.task-state.json" ]; then
        TASK_STATE="$SESSIONS_ROOT/$V11_PROJECT/.task-state.json"
    fi

    # Enforce task requirement if project uses tasks
    if [ -n "$TASK_STATE" ]; then
        # Skip enforcement for trivial projects (fewer than 2 tasks)
        TOTAL=$(jq -r '.total // 0' "$TASK_STATE" 2>/dev/null)

        if [ "$TOTAL" -ge 2 ]; then
            # Must have an in_progress task
            IN_PROGRESS=$(jq -r '.in_progress // 0' "$TASK_STATE" 2>/dev/null)

            if [ "$IN_PROGRESS" -eq 0 ]; then
                cat << EOF
TASK SYSTEM VIOLATION: No task in_progress

Before modifying files in project "$V11_PROJECT", you must:
1. Check available tasks: TaskList
2. Start a task: TaskUpdate(taskId="<id>", status="in_progress")
3. Then modify files
4. When done: TaskUpdate(taskId="<id>", status="completed")

---
Project: $V11_PROJECT | Tasks: $TOTAL total, 0 in_progress
File: $V11_FILE_PATH | Detected via: $V11_DETECTION_METHOD
EOF
                exit 2
            fi
        fi
    fi
fi

# === V11.4: ZERO-TASK ADVISORY NUDGE ===
# When a project has V11 hooks but no tasks, nudge after 5+ writes

if [ -n "$V11_PROJECT" ]; then
    TASK_STATE=""
    if [ -f "$TASK_STATE_DIR/${V11_PROJECT}.json" ]; then
        TASK_STATE="$TASK_STATE_DIR/${V11_PROJECT}.json"
    elif [ -f "$SESSIONS_ROOT/$V11_PROJECT/.task-state.json" ]; then
        TASK_STATE="$SESSIONS_ROOT/$V11_PROJECT/.task-state.json"
    fi

    TASK_TOTAL=0
    if [ -n "$TASK_STATE" ]; then
        TASK_TOTAL=$(jq -r '.total // 0' "$TASK_STATE" 2>/dev/null)
    fi

    # Only nudge if session dir exists (V11 project) but no tasks
    if [ "$TASK_TOTAL" -eq 0 ] && [ -d "$SESSIONS_ROOT/$V11_PROJECT" ]; then
        # Check write count from plan-mode tracking
        if [ -f "$TRACKING_FILE" ]; then
            WRITE_COUNT=$(jq -r '.count // 0' "$TRACKING_FILE" 2>/dev/null)
            if [ "${WRITE_COUNT:-0}" -ge 5 ]; then
                cat << EOF >&2
ADVISORY: V11 project "$V11_PROJECT" has $WRITE_COUNT edits without tasks.
Consider running /v11 to create tasks and enable proof-of-work tracking.
EOF
            fi
        fi
    fi
fi

# === PLAN MODE GUIDANCE (ADVISORY ONLY) ===

# Check plan mode markers - if present, skip tracking
[ -f "$V11_HOME/.plan-mode" ] && exit 0
[ -f "${V11_FILE_PATH%/*}/.plan-mode" ] && exit 0

# Load or initialize tracking state
mkdir -p "$METRICS_DIR"

if [ -f "$TRACKING_FILE" ]; then
    STORED_SESSION=$(jq -r '.session_id // ""' "$TRACKING_FILE" 2>/dev/null)
else
    STORED_SESSION=""
fi

# Reset if session changed or file missing
if [ "$STORED_SESSION" != "$V11_SESSION_ID" ] || [ ! -f "$TRACKING_FILE" ]; then
    jq -n --arg sid "$V11_SESSION_ID" --arg now "$(date -Iseconds)" \
        '{session_id: $sid, files: [], count: 0, last_reset: $now}' \
        > "$TRACKING_FILE"
fi

# Check if file already tracked, add if new
ALREADY=$(jq -r --arg fp "$V11_FILE_PATH" '.files | map(select(. == $fp)) | length' "$TRACKING_FILE")

if [ "$ALREADY" -eq 0 ]; then
    jq --arg fp "$V11_FILE_PATH" \
        '.files += [$fp] | .count = (.files | length)' \
        "$TRACKING_FILE" > "${TRACKING_FILE}.tmp" \
        && mv "${TRACKING_FILE}.tmp" "$TRACKING_FILE"
fi

COUNT=$(jq -r '.count' "$TRACKING_FILE")

# Provide advisory guidance (never blocks)
# V11: Advisory-only with enhanced messaging
if [ "$COUNT" -gt 6 ]; then
    FILE_LIST=$(jq -r '.files[:10][]' "$TRACKING_FILE" 2>/dev/null)
    cat << EOF >&2
ADVISORY: Large change scope detected ($COUNT files modified)

You've modified $COUNT unique files in this session. For changes
of this scope, V11 Protocol recommends using EnterPlanMode to:
  - Document your intent
  - Get user approval
  - Track approval history
  - Improve code review context

Files modified (showing first 10):
$FILE_LIST

You can continue, but plan mode is strongly recommended.
EOF
    # Exit 0 - advisory only, never blocks
    exit 0
fi

if [ "$COUNT" -ge 4 ] && [ "$COUNT" -le 6 ]; then
    cat << EOF >&2
SUGGESTION: Plan mode threshold approaching ($COUNT/6 files)

V11 Protocol suggests using EnterPlanMode when:
  - Making 5+ file modifications
  - Cross-service changes
  - Architecture-impacting edits
  - Multi-day projects

Use 'EnterPlanMode' task to create a formal plan.
EOF
fi

exit 0
