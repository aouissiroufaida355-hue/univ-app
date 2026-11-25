FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Render fournit $PORT ; en local on utilise 8000
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-8000} -w 2 app:app"]
