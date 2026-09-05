import multiprocessing

# Server socket
bind = "0.0.0.0:5000"

# Worker processes
# For I/O-bound app (docker compose ps, HTTP requests), threads help more than workers
workers = 2
threads = 4
worker_class = "gthread"

# Timeout for long-running requests (docker compose ps can take a few seconds)
timeout = 120

# Logging
accesslog = "-"
errorlog = "-"

# Preload app for faster worker startup and shared memory
preload_app = True

# Graceful restart
max_requests = 1000
max_requests_jitter = 50
