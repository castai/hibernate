import functools
import logging

from tenacity import retry, wait_fixed, stop_after_attempt, before_log


def step(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        logging.info(f"============= starting {f.__name__ + ' ':=<40}=============")
        try:
            return f(*args, **kwargs)
        finally:
            logging.info(f"------------- finishing {f.__name__ + ' ':-<40}------------")

    return wrapper


def basic_retry(attempts, pause):
    def decorator_chain(f):
        f = failure_logging(f)
        f = retry(wait=wait_fixed(pause), stop=stop_after_attempt(attempts), before=before_log(logging, logging.INFO))(f)
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
