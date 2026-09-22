def poll():
    try:
        return fetch()
    except TimeoutError:
        return None
