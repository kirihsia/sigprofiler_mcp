# Use the official PyTorch image with CUDA 12.1 pre-installed
FROM pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime

# Set the working directory inside the container
WORKDIR /app

# Copy the entire project into the container
COPY . .

# Install the project and its other dependencies.
# Since 'torch' is already pre-installed in this base image, 
# pip will automatically skip downloading torch and only install the remaining packages.
RUN pip install --no-cache-dir "numpy<2.0" && \
    pip install --no-cache-dir .

# CRITICAL: Disable Python's output buffering
ENV PYTHONUNBUFFERED=1

ENV PYTHONPATH=/app

ENV USE_GPU=True

# Run the entry point script
CMD ["python", "server.py"]
