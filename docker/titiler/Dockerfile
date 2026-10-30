FROM mcr.microsoft.com/azure-functions/python:4-python3.11@sha256:2c39d8b50750fbec9a91ef33323fadd1b986358fab4f7823db5b11b6e533f479

WORKDIR /app

ENV HASTE_GDAL_RUNTIME_REQUIRED=true \
    GDAL_VRT_ENABLE_RAWRASTERBAND=NO \
    GDAL_VRT_ENABLE_PYTHON=NO \
    GDAL_DRIVER_PATH=disable \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED=NO \
    GDAL_SKIP="HDF4 HDF4Image HDF5 HDF5Image netCDF"

COPY api/titilerfuncapi/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt \
    "uvicorn>=0.34,<1"

COPY api/titilerfuncapi /app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
