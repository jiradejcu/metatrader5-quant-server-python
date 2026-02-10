#!/bin/bash

source /scripts/02-common.sh

log_message "RUNNING" "06-install-libraries.sh"

log_message "INFO" "Upgrading pip in Wine environment"
$wine_executable python -m pip install --upgrade pip

log_message "INFO" "Installing MetaTrader5 library and dependencies in Windows"
$wine_executable python -m pip install --no-cache-dir -r /app/requirements.txt