from app.celery_app import celery_app

__all__ = ["celery_app"]

if __name__ == "__main__":
    celery_app.start()
