# Use an ARM64 compatible Python base image
FROM python:3.11.4-slim

# Set the working directory in the container
WORKDIR /app

# Note: Ensure all packages are available for ARM64 architecture in the base image's repository
RUN apt-get update && apt-get install -y \
    libssl-dev \
    gcc \
    libopencv-dev \
    python3-opencv \
    curl \
    libxml2-dev \
    libxslt-dev \
    libffi-dev \
    build-essential \
    cmake \   
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file
COPY requirements.txt ./

# Ensure that all Python packages support ARM64 or have pure Python versions
RUN pip install -r requirements.txt --verbose

# Copy the rest of your application's source code from your host to your image filesystem.
COPY . .

# Run app.py when the container launches
CMD ["python", "app.py"]
