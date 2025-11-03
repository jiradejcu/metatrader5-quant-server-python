# Use the official Python image from the Docker Hub
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project
COPY . /app/

RUN mkdir -p /app/logs && \
    mkdir -p /app/static && \
    chmod 777 /app/logs

RUN python manage.py collectstatic --noinput

# Run the Django development server
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "120", "app.wsgi:application"]