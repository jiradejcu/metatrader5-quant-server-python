import threading

# Lock to ensure thread-safety when reading/writing shared prediction state.
state_lock = threading.Lock()
