#!/bin/bash
# Apply canonical size variables; blank or missing values restore defaults.
set -e
set -o pipefail

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
    echo "Usage: $0 <subscription_id> <resource_prefix> <random_suffix> [dry_run]" >&2
    echo "  Values are read from same-named environment variables; blank = restore default." >&2
    exit 1
fi

SUBSCRIPTION_ID=$1
RESOURCE_PREFIX=$2
RANDOM_SUFFIX=$3
DRY_RUN=${4:-false}

RESOURCE_GROUP="${RESOURCE_PREFIX}-haste-${RANDOM_SUFFIX}-rg"
FUNCTION_API="${RESOURCE_PREFIX}haste${RANDOM_SUFFIX}func"
FUNCTION_QUEUE_API="${RESOURCE_PREFIX}hastequeue${RANDOM_SUFFIX}func"

if [[ "$DRY_RUN" != "true" && "$DRY_RUN" != "false" ]]; then
    echo "ERROR: dry_run must be true or false." >&2
    exit 1
fi

PY_BIN=${PYTHON:-$(command -v python3 || command -v python)}
RESOLVED_LIMITS=$("$PY_BIN" "$(dirname "$0")/resolve_size_limits.py")

# Render a byte count in the largest binary unit that keeps it readable, so a
# 1 MiB floor does not print as "0.00 GiB".
humanize() {
    awk -v b="$1" 'BEGIN {
        if (b >= 1099511627776) printf "%.2f TiB", b / 1099511627776;
        else if (b >= 1073741824) printf "%.2f GiB", b / 1073741824;
        else if (b >= 1048576) printf "%.2f MiB", b / 1048576;
        else printf "%d bytes", b;
    }'
}

API_SETTINGS=()
QUEUE_SETTINGS=()
SUMMARY=""
while IFS='=' read -r KEY BYTES; do
    echo "  $KEY: $BYTES bytes ($(humanize "$BYTES"))"
    SUMMARY="${SUMMARY}| \`$KEY\` | $BYTES | $(humanize "$BYTES") |"$'\n'
    case "$KEY" in
        HASTE_MAX_UPLOAD_BYTES|PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES)
            API_SETTINGS+=("$KEY=$BYTES") ;;
        HASTE_MAX_IMAGERY_DOWNLOAD_BYTES)
            QUEUE_SETTINGS+=("$KEY=$BYTES") ;;
    esac
done <<< "$RESOLVED_LIMITS"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        echo "### Desired size limits"
        echo
        echo "| Setting | Bytes | Human |"
        echo "|---|---|---|"
        printf '%s' "$SUMMARY"
    } >> "$GITHUB_STEP_SUMMARY"
fi

if [ "$DRY_RUN" = "true" ]; then
    echo
    echo "DRY RUN — no changes applied. Targets would be:"
    if [ ${#API_SETTINGS[@]} -gt 0 ]; then
        echo "  $FUNCTION_API: ${API_SETTINGS[*]}"
    fi
    if [ ${#QUEUE_SETTINGS[@]} -gt 0 ]; then
        echo "  $FUNCTION_QUEUE_API: ${QUEUE_SETTINGS[*]}"
    fi
    exit 0
fi

az account set --subscription "$SUBSCRIPTION_ID"

apply_to() {
    local app_name=$1
    shift
    local settings=("$@")
    if [ ${#settings[@]} -eq 0 ]; then
        return 0
    fi

    echo
    echo "+--------------------------------------------------+"
    echo "Updating $app_name"
    echo "+--------------------------------------------------+"

    local pair key expected actual previous
    for pair in "${settings[@]}"; do
        key="${pair%%=*}"
        expected="${pair#*=}"
        previous=$(az functionapp config appsettings list \
            --name "$app_name" --resource-group "$RESOURCE_GROUP" \
            --query "[?name=='$key'].value | [0]" -o tsv)
        echo "  $key: ${previous:-unset (code default)} -> $expected"
        if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
            printf '\n- `%s` on `%s`: `%s` -> `%s`\n' \
                "$key" "$app_name" "${previous:-unset}" "$expected" >> "$GITHUB_STEP_SUMMARY"
        fi
    done

    # Merge semantics: only the listed keys are touched.
    az functionapp config appsettings set \
        --name "$app_name" \
        --resource-group "$RESOURCE_GROUP" \
        --settings "${settings[@]}" \
        --output none

    # Read back what the platform actually stored, rather than trusting the
    # write. A mismatch here means the change did not land.
    for pair in "${settings[@]}"; do
        key="${pair%%=*}"
        expected="${pair#*=}"
        actual=$(az functionapp config appsettings list \
            --name "$app_name" \
            --resource-group "$RESOURCE_GROUP" \
            --query "[?name=='$key'].value | [0]" -o tsv)
        if [ "$actual" != "$expected" ]; then
            echo "ERROR: $key on $app_name reads back as '$actual', expected '$expected'." >&2
            exit 1
        fi
        echo "  verified $key=$actual"
    done
}

apply_to "$FUNCTION_API" "${API_SETTINGS[@]}"
apply_to "$FUNCTION_QUEUE_API" "${QUEUE_SETTINGS[@]}"

# Host key and hostname are resolved *before* any restart. Neither is rotated by
# a restart, and on Flex Consumption the key store stops answering for a few
# seconds afterwards -- reading them post-restart returned empty and failed
# verification outright even though the settings had been written. Retried
# regardless, since the same store can lag just after an app-settings write.
ENDPOINT_ATTEMPTS=${ENDPOINT_ATTEMPTS:-5}
ENDPOINT_RETRY_DELAY=${ENDPOINT_RETRY_DELAY:-5}
declare -A APP_HOST_KEY APP_HOSTNAME

resolve_endpoint() {
    local app_name=$1
    local attempts=0 out

    while [ "$attempts" -lt "$ENDPOINT_ATTEMPTS" ]; do
        attempts=$((attempts + 1))

        if out=$(az functionapp keys list --name "$app_name" \
            --resource-group "$RESOURCE_GROUP" \
            --query "functionKeys.default" -o tsv 2>&1) && [ -n "$out" ]; then
            if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
                echo "::add-mask::$out"
            fi
            APP_HOST_KEY[$app_name]=$out
        else
            echo "  attempt $attempts/$ENDPOINT_ATTEMPTS: no host key for $app_name${out:+ -- $out}" >&2
            sleep "$ENDPOINT_RETRY_DELAY"
            continue
        fi

        if out=$(az functionapp show --name "$app_name" \
            --resource-group "$RESOURCE_GROUP" \
            --query "defaultHostName" -o tsv 2>&1) && [ -n "$out" ]; then
            APP_HOSTNAME[$app_name]=$out
            return 0
        fi

        echo "  attempt $attempts/$ENDPOINT_ATTEMPTS: no hostname for $app_name${out:+ -- $out}" >&2
        sleep "$ENDPOINT_RETRY_DELAY"
    done

    return 1
}

# hastegeo's Config() is instantiated at module import, so workers must recycle
# before a new value takes effect. Changing app settings normally triggers that
# on its own; the explicit restart is belt-and-braces and is allowed to fail
# (the restart CLI is unreliable on Flex Consumption).
restart_app() {
    echo "Restarting $1..."
    if az functionapp restart --name "$1" --resource-group "$RESOURCE_GROUP" --output none 2>/dev/null; then
        echo "  restarted $1"
    else
        echo "  WARNING: restart call failed (known-flaky on Flex Consumption)."
        echo "           The settings write already triggers a worker recycle."
    fi
}

# App-setting key -> the field GetEffectiveLimits reports it under.
declare -A JSON_KEY=(
    [HASTE_MAX_UPLOAD_BYTES]=maxUploadBytes
    [HASTE_MAX_IMAGERY_DOWNLOAD_BYTES]=maxImageryDownloadBytes
    [PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES]=publishAssessmentMaxTotalBytes
)

json_field() {
    printf '%s' "$1" | "$PY_BIN" -c "import json,sys; print(json.load(sys.stdin).get(sys.argv[1],''))" "$2" 2>/dev/null || true
}

# HTTP sampling does not verify every instance or the queue/Batch scale groups.
verify_live() {
    local app_name=$1
    shift
    local settings=("$@")
    if [ ${#settings[@]} -eq 0 ]; then
        return 0
    fi

    echo
    echo "Sampling HTTP worker limits on $app_name..."

    local host_key hostname
    host_key=${APP_HOST_KEY[$app_name]:-}
    hostname=${APP_HOSTNAME[$app_name]:-}

    if [ -z "$host_key" ] || [ -z "$hostname" ] || [ -z "$PY_BIN" ]; then
        echo "  ERROR: could not resolve host key, hostname or a python interpreter." >&2
        echo "         Settings are stored, but HTTP verification could not run." >&2
        return 1
    fi

    local url="https://${hostname}/api/GetEffectiveLimits"
    local attempts=0 streak=0 seen="" body instance live key expected all_match
    local required_streak=5 max_attempts=40

    while [ "$attempts" -lt "$max_attempts" ] && [ "$streak" -lt "$required_streak" ]; do
        attempts=$((attempts + 1))
        body=$(curl -fsS --max-time 20 -H "x-functions-key: $host_key" "$url" 2>/dev/null || true)
        if [ -z "$body" ]; then
            # Expected right after a restart while the app is still coming up.
            streak=0
            sleep 5
            continue
        fi

        all_match=1
        for pair in "${settings[@]}"; do
            key="${pair%%=*}"
            expected="${pair#*=}"
            live=$(json_field "$body" "${JSON_KEY[$key]}")
            if [ "$live" != "$expected" ]; then
                all_match=0
                break
            fi
        done

        instance=$(json_field "$body" instanceId)
        if [ "$all_match" -eq 1 ]; then
            streak=$((streak + 1))
            case "$seen" in
                *"${instance:0:8}"*) ;;
                *) seen="$seen ${instance:0:8}" ;;
            esac
        else
            if [ "$streak" -gt 0 ]; then
                echo "  instance ${instance:0:8} still reports an old limit; resetting streak"
            fi
            streak=0
        fi
        sleep 3
    done

    if [ "$streak" -ge "$required_streak" ]; then
        echo "  HTTP SAMPLE MATCHED: $required_streak consecutive replies report the desired limits."
        echo "  instances sampled:$seen"
        return 0
    fi

    echo "  ERROR: HTTP verification did not converge after $attempts checks." >&2
    echo "         Settings are stored. Check route deployment, connectivity," >&2
    echo "         authentication and worker logs before retrying." >&2
    return 1
}

echo
VERIFY_FAILED=0
if [ ${#API_SETTINGS[@]} -gt 0 ]; then
    resolve_endpoint "$FUNCTION_API" || true
    restart_app "$FUNCTION_API"
fi
if [ ${#QUEUE_SETTINGS[@]} -gt 0 ]; then
    resolve_endpoint "$FUNCTION_QUEUE_API" || true
    restart_app "$FUNCTION_QUEUE_API"
fi

verify_live "$FUNCTION_API" "${API_SETTINGS[@]}" || VERIFY_FAILED=1
verify_live "$FUNCTION_QUEUE_API" "${QUEUE_SETTINGS[@]}" || VERIFY_FAILED=1

TARGETED_APPS=""
if [ ${#API_SETTINGS[@]} -gt 0 ]; then
    TARGETED_APPS="\`$FUNCTION_API\`"
fi
if [ ${#QUEUE_SETTINGS[@]} -gt 0 ]; then
    if [ -n "$TARGETED_APPS" ]; then
        TARGETED_APPS="$TARGETED_APPS, "
    fi
    TARGETED_APPS="$TARGETED_APPS\`$FUNCTION_QUEUE_API\`"
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        echo "### Apply result"
        echo
        echo "Environment resource group: \`$RESOURCE_GROUP\`"
        echo
        echo "Applied to: $TARGETED_APPS"
        echo "HTTP verification failure flag: $VERIFY_FAILED (0 = sampled responses matched)."
        echo "Queue workers and Batch containers were not verified; existing tasks retain their submitted caps."
    } >> "$GITHUB_STEP_SUMMARY"
fi

echo
if [ "$VERIFY_FAILED" -ne 0 ]; then
    echo "FAILED: settings were written but HTTP sampling could not confirm them." >&2
    exit 1
fi
echo "Done: settings stored and sampled HTTP responses matched."
echo "Queue workers and Batch containers were NOT verified. Existing tasks retain their submitted caps."
