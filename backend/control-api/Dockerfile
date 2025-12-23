FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip3 install -r requirements.txt

COPY app/ .

CMD gunicorn --bind 0.0.0.0:${CONTROL_API_PORT} "app:create_app()"