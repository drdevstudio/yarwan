FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Install Xvfb (Virtual Display)
RUN apt-get update && apt-get install -y xvfb

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# Copy the rest of the application
COPY . .

# Run Xvfb in the background and then start the python script
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 & export DISPLAY=:99 && python main.py"]
