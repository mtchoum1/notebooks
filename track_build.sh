#!/bin/bash

# Check if an image name is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <image_name>"
    echo "Example: $0 my_app_image"
    exit 1
fi

IMAGE_NAME="${1}"
BUILD_TYPE="${2}"
DOCKERFILE_PATH="jupyter/${IMAGE_NAME}/ubi9-python-3.11/Dockerfile.${BUILD_TYPE}" # Assuming Dockerfile.cpu is in the current directory or a subdirectory

# --- Log File Setup ---
LOG_DIR="./build_logs"
mkdir -p "${LOG_DIR}" # Create log directory if it doesn't exist
TIMESTAMP=$(date +"%Y-%m-%d_%H%M%S")
LOG_FILE="${LOG_DIR}/build_log_${IMAGE_NAME}_${TIMESTAMP}.txt"

# --- Variables for Averages ---
total_build_time=0.0
total_image_size_mb=0.0
successful_runs=0

echo "Starting podman build tests for image: ${IMAGE_NAME}"
echo "Results will be logged to: ${LOG_FILE}"
echo "-----------------------------------------------------" | tee -a "${LOG_FILE}"
echo "Run,BuildTime(s),ImageSize(MB),ImageCreated(Metadata)" | tee -a "${LOG_FILE}"
echo "-----------------------------------------------------" | tee -a "${LOG_FILE}"

# --- Loop 10 times for build and logging ---
for i in $(seq 1 10); do
    echo "--- Running build ${i}/10 (no-cache) ---" | tee -a "${LOG_FILE}"

    BUILD_TAG="${IMAGE_NAME}:test_run_${i}" # Unique tag for each build

    # Use `time` to measure the execution duration of the podman build command.
    build_duration_raw=$( { time -p podman build \
        --no-cache \
        -q \
        -t "${BUILD_TAG}" \
        --platform linux/amd64 \
        -f "${DOCKERFILE_PATH}" . ; } 2>&1 | awk '/real/ {print $2}' )

    # Check if the podman build command was successful
    if [ $? -ne 0 ]; then
        echo "ERROR: podman build failed for run ${i}!" | tee -a "${LOG_FILE}"
        echo "${i},ERROR,ERROR,ERROR" | tee -a "${LOG_FILE}"
        continue # Skip to the next iteration if build failed
    fi

    echo "Podman build ${i} completed. Retrieving image metadata..."

    # Retrieve image configuration metadata using skopeo.
    image_metadata_config="$(skopeo inspect --retry-times 3 --config "docker-daemon:${BUILD_TAG}")" || {
        echo "ERROR: Couldn't download image config metadata with skopeo tool for ${BUILD_TAG}!" | tee -a "${LOG_FILE}"
        echo "${i},${build_duration_raw},ERROR_SKOPEO,ERROR_SKOPEO" | tee -a "${LOG_FILE}"
        continue # Skip to the next iteration if skopeo fails
    }

    # Extract the 'created' timestamp from the image metadata.
    image_created=$(echo "${image_metadata_config}" | jq --exit-status --raw-output '.created') || {
        echo "ERROR: Couldn't parse '.created' from image metadata for ${BUILD_TAG}!" | tee -a "${LOG_FILE}"
        image_created="N/A" # Set to N/A if parsing fails, but don't stop the run
    }

    # Retrieve raw image metadata for size calculation.
    image_metadata="$(skopeo inspect --retry-times 3 --raw "docker-daemon:${BUILD_TAG}")" || {
        echo "ERROR: Couldn't download raw image metadata with skopeo tool for ${BUILD_TAG}!" | tee -a "${LOG_FILE}"
        echo "${i},${build_duration_raw},ERROR_SKOPEO_RAW,${image_created}" | tee -a "${LOG_FILE}"
        continue
    }

    # Calculate total image size by summing up layer sizes.
    image_size=$(echo "${image_metadata}" | jq --exit-status '[ .layers[].size ] | add') ||  {
        echo "ERROR: Couldn't count image size from image metadata for ${BUILD_TAG}!" | tee -a "${LOG_FILE}"
        echo "${i},${build_duration_raw},ERROR_JQ_SIZE,${image_created}" | tee -a "${LOG_FILE}"
        continue
    }

    # Convert image size from bytes to megabytes using bc for floating-point precision.
    image_size_mb=$(echo "scale=2; ${image_size} / 1024 / 1024" | bc) ||  {
        echo "ERROR: Couldn't calculate image size in MB for ${BUILD_TAG}!" | tee -a "${LOG_FILE}"
        echo "${i},${build_duration_raw},ERROR_CALC_MB,${image_created}" | tee -a "${LOG_FILE}"
        continue
    }

    echo "  Build Duration: ${build_duration_raw} seconds"
    echo "  Image Size: ${image_size_mb} MB"
    echo "  Image Created (metadata): ${image_created}"

    # Log the results
    echo "${i},${build_duration_raw},${image_size_mb},${image_created}" | tee -a "${LOG_FILE}"

    # Add to totals for average calculation
    total_build_time=$(echo "${total_build_time} + ${build_duration_raw}" | bc)
    total_image_size_mb=$(echo "${total_image_size_mb} + ${image_size_mb}" | bc)
    successful_runs=$((successful_runs + 1))

done

echo "-----------------------------------------------------" | tee -a "${LOG_FILE}"
echo "All 10 builds completed. Results are in: ${LOG_FILE}"
echo "-----------------------------------------------------" | tee -a "${LOG_FILE}"

# --- Calculate and Display Averages ---
if [ "${successful_runs}" -gt 0 ]; then
    average_build_time=$(echo "scale=2; ${total_build_time} / ${successful_runs}" | bc)
    average_image_size_mb=$(echo "scale=2; ${total_image_size_mb} / ${successful_runs}" | bc)

    echo "--- Average Results (from ${successful_runs} successful runs) ---" | tee -a "${LOG_FILE}"
    echo "Average Build Time: ${average_build_time} seconds" | tee -a "${LOG_FILE}"
    echo "Average Image Size: ${average_image_size_mb} MB" | tee -a "${LOG_FILE}"
    echo "-------------------------------------------------" | tee -a "${LOG_FILE}"
else
    echo "No successful builds completed to calculate averages." | tee -a "${LOG_FILE}"
fi

# Prune all unused images to clean up.
echo "Pruning all unused images..."
podman image prune --all
echo "Cleanup complete."