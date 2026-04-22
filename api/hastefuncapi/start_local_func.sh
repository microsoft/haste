#!/bin/bash

# Function to install Python 3.11 if not available
ensure_python3_11() {
    if ! python3.11 --version &>/dev/null; then
        echo "Python 3.11 is not installed. Please install it."
        exit 1
    fi
}

# Function to ensure GDAL is installed
ensure_gdal_installed() {
    if ! gdalinfo --version &>/dev/null; then
        echo "GDAL is not installed. Please install it."
        exit 1
    else
        echo "GDAL is already installed."
    fi
}

# Function to setup a virtual environment
setup_venv() {
    if [ ! -d ".venv" ]; then
        echo "Creating a new virtual environment with Python 3.11"
        python3.11 -m venv .venv
    else
        echo "Virtual environment already exists."
    fi

    # Activate the environment
    source .venv/bin/activate

    # Install requirements
    if [ -f "requirements.txt" ]; then
        echo "Installing requirements from requirements.txt"
        pip install -r requirements.txt
    else
        echo "requirements.txt not found."
        exit 1
    fi
}

# Function to install and start Azurite
setup_azurite() {
    if ! which azurite &>/dev/null; then
        echo "Azurite is not installed. Installing Azurite."
        sudo npm install -g azurite
    fi

    # Start Azurite services
    echo "Starting Azurite services..."
    #export AZURITE_ACCOUNTS="account1:key1:key2;account2:key1:key2"
    azurite -l data --loose --debug log.txt > logs_azurerite.txt 2>&1 &
    AZURITE_PID=$!
    echo "Azurite services started with PID $AZURITE_PID"
    echo "Azurite Blob service running at http://localhost:10000"
    echo "Azurite Queue service running at http://localhost:10001"
}

# Check and start Azure Function App
start_function_app() {
    if pgrep -f "func host start" >/dev/null; then
        echo "Azure Function App is already running."
    else
        # Setting up the environment variable for the storage account to use Azurite
        if [ -f "logs_func_api.txt" ]; then
            echo "Deleting existing logs_func_api.txt"
            rm logs_func_api.txt
        fi
        echo "Starting Azure Function App..."
        func host start --verbose > logs_func_api.txt 2>&1 &
        FUNC_PID=$!
        echo "Azure Function App Started with PID $FUNC_PID"
    fi
}

# Function to clean up processes on exit
cleanup() {
    echo "Stopping Azurerite services..."
    kill $FUNC_PID 2>/dev/null
    # Get the PID of the local Azure Function process and kill it
    FUNC_PIDS=$(pgrep -f "func host start")
    if [ -n "$FUNC_PIDS" ] && kill -0 $FUNC_PIDS 2>/dev/null; then
        echo "Stopping Azure Function App with PID $FUNC_PIDS..."
        kill -9 $FUNC_PIDS 2>/dev/null
    fi
    # Uncomment the specific line in requirements.txt
    if grep -q "^#./GDAL-3.9.2-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl" requirements.txt; then
        sed -i.bak 's|^#\(./GDAL-3.9.2-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl\)|\1|' requirements.txt
        echo "Uncommented the GDAL line in requirements.txt"
    fi

    echo "Cleanup complete."
}
# Commenting out a specific line in requirements.txt
if grep -q "./GDAL-3.9.2-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl" requirements.txt; then
    sed -i.bak 's|^./GDAL-3.9.2-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl|#&|' requirements.txt
    echo "Commented out the GDAL line in requirements.txt"
fi
# Set trap to call cleanup on script exit
trap cleanup EXIT
# Main execution flow
ensure_python3_11
ensure_gdal_installed
setup_venv
setup_azurite
start_function_app

# Wait for Azure Function App to exit
wait $FUNC_PID
