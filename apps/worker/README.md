# Worker

The Celery worker reuses the API package.

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

Docker Compose runs the same image as the API with a different command.
