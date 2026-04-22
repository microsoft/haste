#!/bin/bash

# # Create dirs needed by imagery preprocessing

# mkdir -p $AZ_BATCH_TASK_WORKING_DIR/imagery_preprocess/

# Replace all occurrences of 'AZ_BATCH_TASK_WORKING_DIR' in the experiment config
# with the path generated at runtime

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 filename"
    exit 1
fi

filename=$1
search_string="AZ_BATCH_TASK_WORKING_DIR"
replace_string=$AZ_BATCH_TASK_WORKING_DIR

if [ ! -f "$filename" ]; then
    echo "File not found!"
    exit 1
fi

sed -i "s|$search_string|$replace_string|g" "$filename"
echo "Replaced all occurrences of '$search_string' with '$replace_string' in '$filename'."