import functools

CALL_LOG: list[str] = []


def logged(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        CALL_LOG.append(func.__name__)
        return func(*args, **kwargs)

    return wrapper
