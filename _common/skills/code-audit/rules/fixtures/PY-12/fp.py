from datetime import datetime, timezone

def stamp():
    return datetime.now(tz=timezone.utc)
