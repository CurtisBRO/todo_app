# 1. Start with a lightweight Python "base"
FROM python:3.11-slim

# 2. Define where our code lives inside the container
WORKDIR /app

# 3. Copy only the requirements first (this optimizes build speed!)
COPY requirements.txt .

# 4. Install the libraries
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy your main.py into the container
COPY . .

#5.5 Copy the .env file
COPY .env .

# 6. Start the FastAPI server
# We use port 80 so it's a standard web address
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
