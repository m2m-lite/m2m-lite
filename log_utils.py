import logging
import time

from config import relay_config

class CustomFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style="%", converter=None):
        super().__init__(fmt, datefmt, style)
        self.converter = converter or time.localtime

    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created, None)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            t = time.strftime(self.default_time_format, ct)
            s = self.default_msec_format % (t, record.msecs)
        return s

def utc_converter(timestamp, _):
    return time.gmtime(timestamp)

def get_logger(name: str):
    # Configure logging
    logger = logging.getLogger(name)
    log_level = getattr(logging, relay_config["logging"]["level"].upper())
    logger.setLevel(log_level)
    logger.propagate = False

    formatter = CustomFormatter(
        fmt="%(asctime)s %(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        converter=utc_converter,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
