# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import logging
import os

"""
Logger class provides utility methods to create and configure logger instances.

Methods:
    get_logger(name: str, log_file: str = 'app.log', level: int = logging.INFO) -> logging.Logger:

        Example:
            logger = Logger.get_logger('my_logger', 'my_log_file.log', logging.DEBUG)
            logger.info('This is an info message')

    set_log_level(logger: logging.Logger, level: int):

        Example:
            logger = Logger.get_logger('my_logger')
            Logger.set_log_level(logger, logging.WARNING)

    add_file_handler(logger: logging.Logger, log_file: str, level: int = logging.INFO):

        Example:
            logger = Logger.get_logger('my_logger')
            Logger.add_file_handler(logger, 'additional_log_file.log', logging.ERROR)

    add_console_handler(logger: logging.Logger, level: int = logging.ERROR):

        Example:
            logger = Logger.get_logger('my_logger')
            Logger.add_console_handler(logger, logging.DEBUG)
"""


class Logger:
    @staticmethod
    def get_logger(
        name: str,
        log_file: str = "app.log",
        log_dir: str = None,
        level: int = logging.INFO,
    ) -> logging.Logger:
        """
        Creates and returns a logger instance.

        :param name: Name of the logger.
        :param log_file: File to log messages to.
        :param log_dir: Directory to store log files.
        :param level: Logging level.
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(funcName)s - %(lineno)d'
        )
        """
        logger = logging.getLogger(name)
        logger.setLevel(level)
        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(funcName)s - %(lineno)d"
        )

        if not logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        # Check if log directory exists and is writable
        if log_dir and os.path.isabs(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except PermissionError:
                logger.error(
                    f"Permission denied: Unable to create directory {log_dir}"
                )
                return logger
            log_path = os.path.join(log_dir, log_file)
            abs_log_path = os.path.abspath(log_path)
            if not any(
                isinstance(handler, logging.FileHandler)
                and handler.baseFilename == abs_log_path
                for handler in logger.handlers
            ):
                file_handler = logging.FileHandler(log_path)
                file_handler.setLevel(level)
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)

        return logger

    @staticmethod
    def set_log_level(logger: logging.Logger, level: int):
        """
        Sets the logging level for the given logger.

        :param logger: Logger instance.
        :param level: Logging level.
        """
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)

    @staticmethod
    def add_file_handler(
        logger: logging.Logger, log_file: str, level: int = logging.INFO
    ):
        """
        Adds a file handler to the logger.

        :param logger: Logger instance.
        :param log_file: File to log messages to.
        :param level: Logging level.
        """
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(funcName)s - %(lineno)d"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    @staticmethod
    def add_console_handler(
        logger: logging.Logger, level: int = logging.ERROR
    ):
        """
        Adds a console handler to the logger.

        :param logger: Logger instance.
        :param level: Logging level.
        """
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(funcName)s - %(lineno)d"
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    @staticmethod
    def log_error(logger: logging.Logger, message: str):
        """
        Logs an error message.

        :param logger: Logger instance.
        :param message: Error message to log.
        """
        logger.error(message)

    @staticmethod
    def log_info(logger: logging.Logger, message: str):
        """
        Logs an info message.

        :param logger: Logger instance.
        :param message: Info message to log.
        """
        logger.info(message)
