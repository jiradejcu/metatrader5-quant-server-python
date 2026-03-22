import threading

# define variable states here
placing_order_state = {
    "order_id": None,
    "status": None,
    "is_clean": True,
    "fill_pct": 0,
    "side": None,
    'price': None,
    'orig_qty': 0,
    'total_orders': 0
}

# Lock to ensure thread-safety when reading/writing to variable
state_lock = threading.Lock()