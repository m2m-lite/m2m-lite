"""Logging utilities for m2m-lite."""

import logging
import time
import os

from config import relay_config

class CustomFormatter(logging.Formatter):
    """
    Custom formatter that includes milliseconds and allows for UTC time conversion.
    """

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
    """
    Converter function to use UTC time.
    """
    return time.gmtime(timestamp)

def get_logger(name: str, log_file=None):
    """
    Get a logger with the given name.

    :param name: The name of the logger.
    :param log_file: Optional path to a log file.
    :return: The logger instance.
    """
    # Configure logging
    logger = logging.getLogger(name)

    # Get logging level from config, default to INFO
    logging_level_str = relay_config.get("logging", {}).get("level", "INFO").upper()
    log_level = getattr(logging, logging_level_str, logging.INFO)
    logger.setLevel(log_level)
    logger.propagate = False

    formatter = CustomFormatter(
        fmt="%(asctime)s %(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S.%f",  # Include milliseconds in the timestamp
        converter=utc_converter,  # Use UTC time
    )

    # Always log to console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Log to file if enabled in config
    if log_file:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), log_file)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
