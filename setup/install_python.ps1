# Import the class
using namespace System.Runtime.InteropServices

# Check the OS
if ([RuntimeInformation]::IsOSPlatform([OSPlatform]::Windows)) {
    $pythonVersion = & python --version 2>$null
    if ($pythonVersion -notlike "*Python 3.11*") {
        $pythonVersion = $null
    }
    if (-not $pythonVersion) {
        Write-Output "Python 3.11 not found. Installing..."
        winget install -e --id Python.Python.3.11 --scope user --silent-with-progress
        # Add Python to PATH
        $env:Path += ";C:\Program Files\Python311\Scripts\"
        $pythonPath = "python"
        #check if installation succeded
        $pythonVersion = & python --version 2>$null
        if ($pythonVersion -notlike "*Python 3.11*") {
            Write-Error "Python 3.11 installation failed."
            exit 1
        } else {
            Write-Output "Python 3.11 successfully installed."
        }
    } else {
        $pythonPath = "python"
        Write-Output "Python 3.11 is already installed."
    }

    # Check if GDAL is installed
    try {
        $gdalPath = "C:\OSGeo4W\bin\gdalinfo.exe"
        $gdalVersion = & $gdalPath --version 2>$null
    } catch {
        $gdalVersion = $null
    }
    if (-not $gdalVersion) {
            Write-Output "GDAL not found. Installing..."
            # Download and install GDAL using OSGeo4W
            Invoke-WebRequest -Uri "https://download.osgeo.org/osgeo4w/osgeo4w-setup.exe" -OutFile "osgeo4w-setup.exe"
            $originalPath = $env:Path
            $env:Path = "C:\OSGeo4W\bin;$env:Path"
            Start-Process -FilePath "osgeo4w-setup.exe" -ArgumentList "--quiet-mode --no-desktop --site https://download.osgeo.org/osgeo4w/v2 --packages gdal,proj,geos" -NoNewWindow -PassThru -Wait
            $env:Path = $originalPath
            #Remove-Item "osgeo4w-setup.exe"
            # Set GDAL environment variables
            [System.Environment]::SetEnvironmentVariable("GDAL_DATA", "C:\OSGeo4W\share\gdal", [System.EnvironmentVariableTarget]::User)
            [System.Environment]::SetEnvironmentVariable("GDAL_DRIVER_PATH", "C:\OSGeo4W\bin\gdalplugins", [System.EnvironmentVariableTarget]::User)
            $currentPath = [System.Environment]::GetEnvironmentVariable("PATH", [System.EnvironmentVariableTarget]::User)
            if ($currentPath -notlike "*C:\OSGeo4W\bin*") {
                [System.Environment]::SetEnvironmentVariable("PATH", "$currentPath;C:\OSGeo4W\bin", [System.EnvironmentVariableTarget]::User)
            }

             # Validate GDAL installation
            $gdalVersion = & $gdalPath --version 2>$null

            if (-not $gdalVersion) {
                Write-Error "GDAL installation failed."
                exit 1
            } else {
                Write-Output "GDAL successfully installed."
            }
            
        } else {
            Write-Output "GDAL is already installed."
            [System.Environment]::SetEnvironmentVariable("GDAL_DATA", "C:\OSGeo4W\share\gdal", [System.EnvironmentVariableTarget]::User)
            [System.Environment]::SetEnvironmentVariable("GDAL_DRIVER_PATH", "C:\OSGeo4W\bin\gdalplugins", [System.EnvironmentVariableTarget]::User)
            $currentPath = [System.Environment]::GetEnvironmentVariable("PATH", [System.EnvironmentVariableTarget]::User)
            if ($currentPath -notlike "*C:\OSGeo4W\bin*") {
                [System.Environment]::SetEnvironmentVariable("PATH", "$currentPath;C:\OSGeo4W\bin", [System.EnvironmentVariableTarget]::User)
            }
        }
    } elseif ([RuntimeInformation]::IsOSPlatform([OSPlatform]::OSX)) {
            $pythonVersion = & sh -c "python3.11 --version" 2>$null
            if (-not $pythonVersion) {
                Write-Output "Python 3.11 not found. Installing..."
                /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
                brew install python@3.11
                $pythonPath = "/usr/local/bin/python3.11"
                $pythonVersion = & sh -c "python3.11 --version" 2>$null
                if (-not $pythonVersion) {
                    Write-Error "Python 3.11 installation failed."
                    exit 1
                } else {
                    Write-Output "Python 3.11 successfully installed."
                }
            } else {
                $pythonPath = "python3.11"
                Write-Output "Python 3.11 is already installed."
            }
            # Check if GDAL is installed
            $gdalVersion = & gdalinfo --version 2>$null
            if (-not $gdalVersion) {
                Write-Output "GDAL not found. Installing..."
                brew install gdal
                # Validate GDAL installation
                $gdalVersion = & gdalinfo --version 2>$null
                if (-not $gdalVersion) {
                    Write-Error "GDAL installation failed."
                    exit 1
                } else {
                    Write-Output "GDAL successfully installed."
                }
            } else {
                Write-Output "GDAL is already installed."
            }
} elseif ([RuntimeInformation]::IsOSPlatform([OSPlatform]::Linux)) {
    $pythonVersion = & sh -c "python3.11 --version" 2>$null
    if (-not $pythonVersion) {
        Write-Output "Python 3.11 not found. Installing..."
        sudo apt-get update
        sudo apt-get install -y python3.11
        $pythonPath = "python3.11"
        $pythonVersion = & sh -c "python3.11 --version" 2>$null
        if (-not $pythonVersion) {
            Write-Error "Python 3.11 installation failed."
            exit 1
        } else {
            Write-Output "Python 3.11 successfully installed."
        }
    } else {
        $pythonPath = "python3.11"
        Write-Output "Python 3.11 is already installed."
    }
    # Check if GDAL is installed
    $gdalVersion = & gdalinfo --version 2>$null
    if (-not $gdalVersion) {
        Write-Output "GDAL not found. Installing..."
        sudo apt-get update
        sudo apt-get install -y gdal-bin
        # Validate GDAL installation
        $gdalVersion = & gdalinfo --version 2>$null
        if (-not $gdalVersion) {
            Write-Error "GDAL installation failed."
            exit 1
        } else {
            Write-Output "GDAL successfully installed."
        }
    } else {
        Write-Output "GDAL is already installed."
    }
} else {
    Write-Output "Unknown operating system."
    exit
}

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::Machine) + ";" + [System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::User)



# Commenting or uncommenting a specific line in requirements.txt
$requirementsPath = "../api/hastefuncapi/requirements.txt"
$gdalLine = "./GDAL-3.9.2-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"

if (Test-Path $requirementsPath) {
    $content = Get-Content $requirementsPath
    if ($content -contains $gdalLine) {
        $content = $content -replace "^$([regex]::Escape($gdalLine))", "#$gdalLine"
        Set-Content -Path $requirementsPath -Value $content
        Write-Output "Commented out the GDAL line in requirements.txt"
    } elseif ($content -contains "#$gdalLine") {
        $content = $content -replace "^#$([regex]::Escape($gdalLine))", "$gdalLine"
        Set-Content -Path $requirementsPath -Value $content
        Write-Output "Uncommented the GDAL line in requirements.txt"
    }
} else {
    Write-Output "requirements.txt not found."
}
