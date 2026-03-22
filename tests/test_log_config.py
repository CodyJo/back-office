"""Tests for backoffice.log_config."""
import logging

from backoffice.log_config import setup_logging


def test_setup_logging_configures_backoffice_logger():
    setup_logging()
    logger = logging.getLogger("backoffice")
    assert logger.level == logging.INFO
    assert len(logger.handlers) >= 1


def test_setup_logging_verbose_sets_debug():
    setup_logging(verbose=True)
    logger = logging.getLogger("backoffice")
    assert logger.level == logging.DEBUG


def test_setup_logging_json_mode():
    setup_logging(json_output=True)
    logger = logging.getLogger("backoffice")
    handler = logger.handlers[-1]
    assert "JSONFormatter" in type(handler.formatter).__name__


def test_logger_outputs_to_stderr(capsys):
    setup_logging()
    logger = logging.getLogger("backoffice.test")
    logger.info("test message")
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing on stdout
