#!/bin/bash

# Define variables for clarity
MAKE_COMMAND="gmake jupyter-minimal-ubi9-python-3.11 -e RELEASE_PYTHON_VERSION=3.11 -e IMAGE_REGISTRY=\"quay.io/rh-ee-mtchoumi/workbench-images\" -e RELEASE=\"2025b\" -e CONTAINER_BUILD_CACHE_ARGS=\"--no-cache\" -e PUSH_IMAGES=\"no\""
IMAGE_NAME="quay.io/rh-ee-mtchoumi/workbench-images:jupyter-minimal-ubi9-python-3.11-2025b_$(date +%Y%m%d)"
LOG_FILE="build_and_size_log.txt"

echo "--- Script started on $(date) ---" | tee -a "$LOG_FILE"

# Track the start time of the gmake command
START_TIME=$(date +%s)

echo "Running command: $MAKE_COMMAND" | tee -a "$LOG_FILE"
# Execute the gmake command
eval "$MAKE_COMMAND"

# Check the exit status of the gmake command
if [ $? -eq 0 ]; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    echo "Gmake command completed successfully." | tee -a "$LOG_FILE"
    echo "Time taken for gmake command: $DURATION seconds" | tee -a "$LOG_FILE"

    echo "Getting image size for: $IMAGE_NAME" | tee -a "$LOG_FILE"
    # Get image size using podman inspect
    PODMAN_OUTPUT=$(podman inspect "$IMAGE_NAME" 2>/dev/null)

    if [ $? -eq 0 ]; then
        IMAGE_SIZE_BYTES=$(echo "$PODMAN_OUTPUT" | grep -m 1 '"Size":' | awk '{print $2}' | sed 's/,//')
        
        if [ -n "$IMAGE_SIZE_BYTES" ]; then
            # Convert bytes to human-readable units
            if (( IMAGE_SIZE_BYTES >= 1099511627776 )); then
                IMAGE_SIZE=$(awk "BEGIN {printf \"%.2f TB\", $IMAGE_SIZE_BYTES / 1099511627776}")
            elif (( IMAGE_SIZE_BYTES >= 1073741824 )); then
                IMAGE_SIZE=$(awk "BEGIN {printf \"%.2f GB\", $IMAGE_SIZE_BYTES / 1073741824}")
            elif (( IMAGE_SIZE_BYTES >= 1048576 )); then
                IMAGE_SIZE=$(awk "BEGIN {printf \"%.2f MB\", $IMAGE_SIZE_BYTES / 1048576}")
            elif (( IMAGE_SIZE_BYTES >= 1024 )); then
                IMAGE_SIZE=$(awk "BEGIN {printf \"%.2f KB\", $IMAGE_SIZE_BYTES / 1024}")
            else
                IMAGE_SIZE="${IMAGE_SIZE_BYTES} Bytes"
            fi
            echo "Image size: $IMAGE_SIZE" | tee -a "$LOG_FILE"
        else
            echo "Could not extract image size from podman inspect output." | tee -a "$LOG_FILE"
        fi
    else
        echo "Error: podman inspect failed for $IMAGE_NAME. Image might not exist or podman is not configured." | tee -a "$LOG_FILE"
    fi
else
    echo "Error: Gmake command failed to complete successfully." | tee -a "$LOG_FILE"
fi

echo "--- Script finished on $(date) ---" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE" # Add a blank line for readability between runs

echo "Script execution completed. Check '$LOG_FILE' for details."