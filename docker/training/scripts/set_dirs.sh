#!/bin/bash

# Resolve the canonical task working directory.
#
# HASTE_JOB_WORKDIR is the provider-neutral canonical variable for the
# writable working directory of this job. AZ_BATCH_TASK_WORKING_DIR is the
# legacy Azure Batch variable, kept as a compatibility alias so
# already-published images and not-yet-migrated adapters keep working.
# HASTE_JOB_WORKDIR always wins when both are set (and may differ):
# legacy-only environments populate HASTE_JOB_WORKDIR from
# AZ_BATCH_TASK_WORKING_DIR, then AZ_BATCH_TASK_WORKING_DIR is
# unconditionally re-exported to match the resolved HASTE_JOB_WORKDIR, so
# downstream consumers (including the literal AZ_BATCH_TASK_WORKING_DIR
# placeholder still emitted by processors below) never see a stale/divergent
# legacy value.
if [ -z "${HASTE_JOB_WORKDIR:-}" ] && [ -z "${AZ_BATCH_TASK_WORKING_DIR:-}" ]; then
    echo "Error: neither HASTE_JOB_WORKDIR nor AZ_BATCH_TASK_WORKING_DIR is set." >&2
    exit 1
fi

export HASTE_JOB_WORKDIR="${HASTE_JOB_WORKDIR:-$AZ_BATCH_TASK_WORKING_DIR}"
export AZ_BATCH_TASK_WORKING_DIR="$HASTE_JOB_WORKDIR"

# Setup environment variables to point to writable dirs

export TORCH_HOME=$HASTE_JOB_WORKDIR/
export MPLCONFIGDIR=$HASTE_JOB_WORKDIR/

# Create dirs needed by damage assessment model

mkdir -p $HASTE_JOB_WORKDIR/masks/ $HASTE_JOB_WORKDIR/images/

# Replace all occurrences of 'AZ_BATCH_TASK_WORKING_DIR' in the experiment config
# with the path generated at runtime. Processors still emit this literal
# placeholder string in generated config files; the value substituted here is
# the resolved HASTE_JOB_WORKDIR path regardless of which variable the
# adapter originally set.

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 filename"
    exit 1
fi

filename=$1
search_string="AZ_BATCH_TASK_WORKING_DIR"
replace_string=$HASTE_JOB_WORKDIR

if [ ! -f "$filename" ]; then
    echo "File not found!"
    exit 1
fi

sed -i "s|$search_string|$replace_string|g" "$filename"
echo "Replaced all occurrences of '$search_string' with '$replace_string' in '$filename'."