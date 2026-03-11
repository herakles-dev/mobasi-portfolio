#!/bin/bash
# V11 Hook: guard-enforcement (PreToolUse — Write|Edit|Bash)
# Consolidated enforcement hook: combines guard-risk + guard-autonomy + tool policy cascade.
# Checks risk level, tool policies (V11), and autonomy grants.
#
# Performance: 2 hooks → 1 hook (reduces PreToolUse overhead by ~50ms)
# V11: Added tool policy cascade with deny-wins semantics.
#
# Exit codes:
#   0 - Allow operation (low risk or auto-approved)
#   2 - Block operation (high-risk without approval, policy violation, or medium-risk without grant)

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

# Test mode
if [ "$1" == "--test" ]; then
    echo "guard-enforcement v2 (consolidated: risk + autonomy + tool-policy)"
    exit 0
fi

# Parse hook input
v11_parse_input

# Only guard Write, Edit, and Bash
case "$V11_TOOL_NAME" in
    Write|Edit|Bash) ;;
    *) exit 0 ;;
esac

# Bash: check risk level (includes high-risk blocking)
if [ "$V11_TOOL_NAME" == "Bash" ]; then
    [ -z "$V11_COMMAND" ] && exit 0

    # v11_check_risk handles high-risk blocking + A4 auto-approval
    if ! v11_check_risk; then
        exit 2  # High-risk blocked
    fi
fi

# Detect project from file path or command for downstream checks
v11_detect_project "$V11_FILE_PATH"
if [ -z "$V11_PROJECT" ] && [ -n "$V11_COMMAND" ]; then
    CMD_PATH=$(printf '%s' "$V11_COMMAND" | grep -oE "$HERCULES_ROOT/[^ ]+" | head -1)
    [ -n "$CMD_PATH" ] && v11_detect_project "$CMD_PATH"
fi

# === V11: Tool Policy Cascade (deny-wins) ===
# Only active inside formations with agent identity set.
# Checks formation defaults → role overrides → deny lists.
if [ -n "${V11_AGENT_ID:-}" ]; then
    # Look for formation registry in current dir or session dir
    POLICY_REGISTRY=""
    if [ -f ".formation-registry.json" ]; then
        POLICY_REGISTRY=".formation-registry.json"
    elif [ -n "$V11_PROJECT" ] && [ -f "$SESSIONS_ROOT/$V11_PROJECT/.formation-registry.json" ]; then
        POLICY_REGISTRY="$SESSIONS_ROOT/$V11_PROJECT/.formation-registry.json"
    fi

    if [ -n "$POLICY_REGISTRY" ]; then
        POLICY_RESULT=""
        POLICY_RESULT=$(v11_resolve_tool_policy "$V11_TOOL_NAME" "$POLICY_REGISTRY" 2>/dev/null)
        if [ $? -ne 0 ]; then
            cat << EOF
TOOL POLICY VIOLATION: $V11_TOOL_NAME denied for agent $V11_AGENT_ID

$POLICY_RESULT

Resolution: Create a task for a teammate with the appropriate permissions,
or ask the team lead to override the policy in .formation-registry.json.
EOF
            exit 2
        fi
    fi
fi

# Check autonomy grants for medium-risk operations
# v11_check_autonomy returns 0 if auto-approved, 1 if needs manual approval
if ! v11_check_autonomy; then
    # Medium-risk operation without autonomy grant
    # Don't block here - let user proceed with awareness
    # (Other hooks like guard-task-state will enforce workflow)
    exit 0
fi

exit 0
