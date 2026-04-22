# Use the official TiTiler image from developmentseed
FROM developmentseed/titiler:latest

# Expose the port that TiTiler runs on
EXPOSE 8000

# Command to run the TiTiler API (module path changed in newer versions)
CMD ["uvicorn", "titiler.application.main:app", "--host", "0.0.0.0", "--port", "8000"]