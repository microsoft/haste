# Use the official TiTiler image from developmentseed
FROM developmentseed/titiler:latest

# Defense-in-depth GDAL configuration. The application runtime policy also
# deregisters VRT and enforces this configuration before serving requests.
ENV GDAL_VRT_ENABLE_RAWRASTERBAND=NO \
    GDAL_VRT_ENABLE_PYTHON=NO \
    GDAL_DRIVER_PATH=disable \
    CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED=NO
ENV GDAL_SKIP="VRT HDF4 HDF4Image HDF5 HDF5Image netCDF"

# Expose the port that TiTiler runs on
EXPOSE 8000

# Command to run the TiTiler API (module path changed in newer versions)
CMD ["uvicorn", "titiler.application.main:app", "--host", "0.0.0.0", "--port", "8000"]