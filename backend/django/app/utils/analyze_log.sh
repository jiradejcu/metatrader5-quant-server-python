# django container bash
# usage: ./analyze_log.sh /app/logs/quant.log.20xx-xx-xx

LOG_FILE="$1"

if [ -z "$LOG_FILE" ]; then
    echo "usage: $0 <log_file>"
    exit 1
fi

python plots.py --price-diff "$LOG_FILE"
python plots.py --stale-ticker "$LOG_FILE"
python analyze_orders.py "$LOG_FILE"
