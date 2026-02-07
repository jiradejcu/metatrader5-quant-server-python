FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ .

CMD gunicorn --bind 0.0.0.0:${CONTROL_API_PORT} --worker-class gevent --timeout 0  "app:create_app()"