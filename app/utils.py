import functools
import logging
import requests
from tenacity import retry, wait_fixed, stop_after_attempt, before_log, retry_if_exception_type


def step(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        logging.info(f"============= starting {f.__name__ + ' ':=<40}=============")
        try:
            return f(*args, **kwargs)
        finally:
            logging.info(f"------------- finishing {f.__name__ + ' ':-<40}------------")

    return wrapper


def _is_retryable_error(exc: BaseException) -> bool:
    """Return True only for transient errors worth retrying."""
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    if isinstance(exc, requests.exceptions.ConnectionError):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        # Retry on 5xx server errors, but fail fast on 4xx client errors
        resp = exc.response
        if resp is not None and 500 <= resp.status_code < 600:
            return True
        return False
    return False


def basic_retry(attempts, pause):
    def decorator_chain(f):
        f = failure_logging(f)
        f = retry(
            wait=wait_fixed(pause),
            stop=stop_after_attempt(attempts),
            before=before_log(logging, logging.INFO),
            retry=retry_if_exception_type(_is_retryable_error),
        )(f)
        return f

    return decorator_chain


def failure_logging(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as err:
            logging.error(f"Call failed [{f.__name__}]: {err}")
            raise err

    return wrapper

def parse_labels(labels: str) -> dict:
    """Parse and validate labels from a string"""
    label_dict = {}
    for label in labels.split(","):
        key_value = label.split("=")
        if len(key_value) == 2:
            key, value = key_value
            key = key.strip()
            if key in label_dict:
                logging.warning(f"Duplicate key detected: {key}")
            label_dict[key] = value.strip()
        else:
            logging.warning(f"Invalid label format: {label}")
    return label_dict