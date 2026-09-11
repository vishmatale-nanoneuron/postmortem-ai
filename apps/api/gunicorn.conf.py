"""Gunicorn configuration for the container / self-hosted path.

Production today runs on Vercel, which invokes the ASGI app directly
("framework": "fastapi" in vercel.json) -- nothing here applies there. This
is for apps/api/Dockerfile, the image CI builds and scans on every run so
that moving to a container host is a configuration change, not a rebuild.
Until now that image ran a single bare uvicorn process: one worker, no
request timeout, no recycling, nothing supervising it.

Gunicorn supervises N uvicorn workers (uvicorn-worker is the maintained
worker class; uvicorn.workers is deprecated). Every value below is
overridable by environment variable so the same image works on a 1-vCPU
box and a 16-vCPU one.
"""

import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
worker_class = "uvicorn_worker.UvicornWorker"

# Async workers: 2*CPU+1 is the usual sync-worker rule and is too many for
# an async app that is mostly waiting on Postgres and the model provider;
# one worker per CPU keeps memory (and the per-worker connection pool the
# lifespan opens) proportional to the box. WEB_CONCURRENCY is the
# conventional override, honoured by Heroku-style platforms too.
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count()))

# A draft is one model round-trip on a long evidence prompt; the ai_runs
# table shows several seconds typical. Gunicorn's default of 30s would kill
# a worker mid-draft on a slow provider day and the client would see a
# blank 502 with no ai_runs row written. 120s is comfortably above any
# legitimate request and still bounds a hung one.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))

# Recycle workers periodically so a slow leak in any dependency cannot grow
# forever; jitter so the workers do not all restart at the same moment.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "100"))

# The worker heartbeat file goes on tmpfs; on a container with a slow or
# overlay filesystem, the default /tmp can stall the heartbeat and make the
# arbiter kill healthy workers.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None

# Behind a reverse proxy or load balancer, which is the only sane way to
# expose this; the app reads X-Forwarded-* for the client IP the rate
# limiter keys on.
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "*")

# Both logs to stdout/stderr, where a container runtime collects them.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
# The Vercel/uvicorn-style access line, minus nothing the app logs itself.
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'
