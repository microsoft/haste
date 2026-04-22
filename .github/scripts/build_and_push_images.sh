#!/bin/bash
set -euo pipefail

# Docker Build and Push Script for Azure Container Registry - Multi-Image Support
# This script can build single or multiple Docker images based on the IMAGE_DIR parameter

# Color codes for better output readability
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Default values (can be overridden by environment variables or command line)
IMAGE_DIR=${IMAGE_DIR:-"all"}
IMAGE_TAG=${IMAGE_TAG:-"test-build"}
ACR_NAME=${ACR_NAME:-""}
REPO_DIR=${REPO_DIR:-$(pwd)}

# Function to print colored output (GitHub Actions aware)
log_info() {
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        echo "::notice::$1"
    else
        echo -e "${BLUE}[INFO]${NC} $1"
    fi
}

log_success() {
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        echo "::notice::✅ $1"
    else
        echo -e "${GREEN}[SUCCESS]${NC} $1"
    fi
}

log_warning() {
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        echo "::warning::$1"
    else
        echo -e "${YELLOW}[WARNING]${NC} $1"
    fi
}

log_error() {
    if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        echo "::error::$1"
    else
        echo -e "${RED}[ERROR]${NC} $1" >&2
    fi
}

# Function to display usage
usage() {
    echo "Usage: $0 [-t image_tag] [-i image_dir] [-a acr_name] [-r repo_dir]"
    echo "  -t image_tag    : Docker image tag (default: latest)"
    echo "  -i image_dir    : Image directory to build (default: all)"
    echo "  -a acr_name     : Azure Container Registry name"
    echo "  -r repo_dir     : Repository root directory (default: current directory)"
    echo ""
    echo "Valid image directory names: training, imageryprep, all"
    echo "'all' will build both training and imageryprep images"
    echo ""
    echo "Environment variables can also be used:"
    echo "  ACR_NAME, IMAGE_DIR, IMAGE_TAG, REPO_DIR"
    exit 1
}

# Parse command line options
while getopts ":t:i:a:r:h" opt; do
    case ${opt} in
        t )
            IMAGE_TAG=$OPTARG
            ;;
        i )
            IMAGE_DIR=$OPTARG
            ;;
        a )
            ACR_NAME=$OPTARG
            ;;
        r )
            REPO_DIR=$OPTARG
            ;;
        h )
            usage
            ;;
        \? )
            log_error "Invalid option: -$OPTARG"
            usage
            ;;
        : )
            log_error "Option -$OPTARG requires an argument"
            usage
            ;;
    esac
done

# Function to validate inputs
validate_inputs() {
    if [[ -z "$ACR_NAME" ]]; then
        log_error "ACR_NAME is required. Set it via environment variable or -a flag"
        exit 1
    fi

    if [[ -z "$IMAGE_DIR" ]] || [[ -z "$IMAGE_TAG" ]]; then
        log_error "IMAGE_DIR and IMAGE_TAG are required"
        usage
    fi

    # Validate IMAGE_DIR against enumerated values
    case $IMAGE_DIR in
        training|imageryprep|all)
            ;;
        *)
            log_error "Invalid image directory '$IMAGE_DIR'"
            log_error "Valid options: training, imageryprep, all"
            usage
            ;;
    esac

    if [[ ! -d "$REPO_DIR" ]]; then
        log_error "Repository directory not found: $REPO_DIR"
        exit 1
    fi
}

# Function to determine which images to build
get_images_to_build() {
    local images_to_build=()
    
    if [[ "$IMAGE_DIR" == "all" ]]; then
        # Only build training and imageryprep for "all"
        images_to_build=("training" "imageryprep")
    else
        if [[ -d "$REPO_DIR/docker/$IMAGE_DIR" ]]; then
            images_to_build=("$IMAGE_DIR")
        else
            log_error "Docker directory not found: $REPO_DIR/docker/$IMAGE_DIR"
            exit 1
        fi
    fi
    
    if [[ ${#images_to_build[@]} -eq 0 ]]; then
        log_error "No valid Docker directories found to build"
        exit 1
    fi
    
    echo "${images_to_build[@]}"
}

# Function to build and push a single image using ACR Tasks
build_and_push_image() {
    local image_dir="$1"
    
    if [[ -z "$image_dir" ]]; then
        log_error "Image directory parameter is required"
        return 1
    fi
    
    local image_name="haste${image_dir}"
    local image_tag_for_acr="${image_name}:${IMAGE_TAG}"
    local acr_fqdn="${ACR_NAME}.azurecr.io"
    local full_image_name="${acr_fqdn}/${image_tag_for_acr}"
    local dockerfile_relative_path="docker/$image_dir/Dockerfile"
    local dockerfile_absolute_path="$REPO_DIR/$dockerfile_relative_path"

    log_info "Building image: $image_name with tag: $IMAGE_TAG"
    log_info "Full image name: $full_image_name"

    # Validate Dockerfile exists
    if [[ ! -f "$dockerfile_absolute_path" ]]; then
        log_error "Dockerfile not found: $dockerfile_absolute_path"
        return 1
    fi

    # Perform Docker cleanup
    log_info "Performing Docker system cleanup..."
    docker system prune -af || log_warning "Docker cleanup failed, continuing..."

    # Construct az acr build command
    local az_acr_build_cmd=(
        az acr build
        --registry "$ACR_NAME"
        --image "$image_tag_for_acr"
        --file "$dockerfile_relative_path"
        "$REPO_DIR"
    )

    # Add subscription if available
    if [[ -n "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
        az_acr_build_cmd=(
            az acr build
            --subscription "$AZURE_SUBSCRIPTION_ID"
            --registry "$ACR_NAME"
            --image "$image_tag_for_acr"
            --file "$dockerfile_relative_path"
            "$REPO_DIR"
        )
    fi

    log_info "Executing ACR build: ${az_acr_build_cmd[*]}"
    
    # Execute the command
    if "${az_acr_build_cmd[@]}"; then
        log_success "Successfully built and pushed: $full_image_name"
        return 0
    else
        log_error "Failed to build image: $image_name"
        return 1
    fi
}

# Function to check ACR login
check_acr_login() {
    log_info "Verifying ACR access to $ACR_NAME..."
    
    # Try to login to ACR
    if ! az acr login --name "$ACR_NAME"; then
        log_error "Failed to login to ACR. Please ensure you're authenticated with Azure CLI"
        exit 1
    fi
    
    log_success "Successfully authenticated with ACR"
}

# Main execution
main() {
    log_info "Starting Docker multi-image build and push process..."
    
    # Show configuration
    log_info "Configuration:"
    log_info "  ACR_NAME: $ACR_NAME"
    log_info "  IMAGE_DIR: $IMAGE_DIR"
    log_info "  IMAGE_TAG: $IMAGE_TAG"
    log_info "  REPO_DIR: $REPO_DIR"
    
    # Validate inputs
    validate_inputs
    
    # Get list of images to build
    local images_to_build
    images_to_build=($(get_images_to_build))
    
    log_info "Images to build: ${images_to_build[*]}"
    
    # Check ACR login
    check_acr_login
    
    # Build and push each image
    local success_count=0
    local total_count=${#images_to_build[@]}
    
    for image_dir in "${images_to_build[@]}"; do
        log_info "Building image for directory: $image_dir"
        
        if build_and_push_image "$image_dir"; then
            success_count=$((success_count + 1))
            log_success "Successfully completed: $image_dir"
        else
            log_error "Failed to process: $image_dir"
        fi
    done
    
    # Final results
    if [[ $success_count -eq $total_count ]]; then
        log_success "All $total_count images built and pushed successfully!"
        exit 0
    else
        log_error "Only $success_count out of $total_count images were successful"
        exit 1
    fi
}

# Execute main function
main "$@"
