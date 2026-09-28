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

# Wait up to 120 seconds for the server to listen. It needs longer than a few
# seconds, because app.py connects to the MT5 terminal before it binds the port.
for _ in $(seq 1 60); do
    if ss -tln | grep -q ':5001'; then
        log_message "INFO" "Flask server started successfully."
        exit 0
    fi
    sleep 2
done

log_message "ERROR" "Failed to start Flask server."
exit 1