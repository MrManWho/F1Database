FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV F1_TRACKER_DATA_DIR=/data PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "server.py"]
