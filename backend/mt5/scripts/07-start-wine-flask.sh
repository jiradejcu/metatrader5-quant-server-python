#!/bin/bash

source /scripts/02-common.sh

log_message "RUNNING" "07-start-wine-flask.sh"

log_message "INFO" "Starting Flask server in Wine environment..."

while true; do
    if [ "${DEBUGPY_ENABLED:-false}" = "true" ]; then
        log_message "INFO" "Starting with debugpy on 0.0.0.0:5678..."
        pkill -f "debugpy.adapter" 2>/dev/null || true
        sleep 1
        wine python -m debugpy --listen 0.0.0.0:5678 /app/app.py
    else
        wine python /app/app.py
    fi

    log_message "ERROR" "Flask server exited. Restarting in 5 seconds..."
    sleep 5
done &

# Give the server some time to start
sleep 5

# Check if the Flask server is running
if ss -tlnp | grep -q ':5001'; then
    log_message "INFO" "Flask server started successfully."
else
    log_message "ERROR" "Failed to start Flask server."
    exit 1
fi