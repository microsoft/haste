#!/bin/bash

# Variables
ACR_NAME=<REPLACE_ME>
IMAGE_DIR=all
IMAGE_TAG=latest
REPO_DIR=$(pwd)

# Function to display usage
usage() {
    echo "Usage: $0 [-t image_tag] [-i image_dir]"
    # corresponds to the docker directory name
    echo "Valid image directory names: training, imageryprep, all"
    echo '"all" will build both images'
    exit 1
}

# Parse named options
while getopts ":t:i:" opt; do
    case ${opt} in
        t )
            IMAGE_TAG=$OPTARG
            ;;
        i )
            IMAGE_DIR=$OPTARG
            ;;
        \? )
            usage
            ;;
    esac
done

# Ensure IMAGE_NAME and IMAGE_TAG are set
if [ -z "$IMAGE_DIR" ] || [ -z "$IMAGE_TAG" ]; then
    usage
fi

# Validate IMAGE_NAME against enumerated values
case $IMAGE_DIR in
    training|imageryprep|all)
        ;;
    *)
        echo "Error: Invalid image name '$IMAGE_NAME'."
        usage
        ;;
esac

if [ "$IMAGE_DIR" == "all" ]; then
    IMAGES_TO_BUILD=("training" "imageryprep")
else
    IMAGES_TO_BUILD=("$IMAGE_DIR")
fi

echo "Building images: ${IMAGES_TO_BUILD[@]} with tag: $IMAGE_TAG"

# Login to Azure Container Registry
az acr login --name $ACR_NAME

for IMAGE_DIR in "${IMAGES_TO_BUILD[@]}"; do

    IMAGE_NAME="haste$IMAGE_DIR"
    echo "Building image: $IMAGE_NAME with tag: $IMAGE_TAG"

    # Build and tag the Docker image
    echo "Command: docker build -t $ACR_NAME.azurecr.io/$IMAGE_NAME:$IMAGE_TAG -f $REPO_DIR/docker/$IMAGE_DIR/Dockerfile $REPO_DIR"
    docker build -t "$ACR_NAME.azurecr.io/$IMAGE_NAME:$IMAGE_TAG" -f "$REPO_DIR/docker/$IMAGE_DIR/Dockerfile" "$REPO_DIR"
    if [ $? -ne 0 ]; then
        echo "Error building image $IMAGE_NAME:$IMAGE_TAG"
        exit 1
    fi
    echo "Image $IMAGE_NAME:$IMAGE_TAG built successfully."

    # Push the Docker image to ACR
    echo "Pushing image: $IMAGE_NAME with tag: $IMAGE_TAG to registry: $ACR_NAME.azurecr.io"
    docker push "$ACR_NAME.azurecr.io/$IMAGE_NAME:$IMAGE_TAG"
    if [ $? -ne 0 ]; then
        echo "Error pushing image $IMAGE_NAME:$IMAGE_TAG"
        exit 1
    fi
    echo "Image $IMAGE_NAME:$IMAGE_TAG pushed to $ACR_NAME.azurecr.io successfully."
done
echo "Done"