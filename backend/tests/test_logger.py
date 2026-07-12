import logging
import sys

from pythonjsonlogger import jsonlogger

from logger import logger as module_logger
from logger import setup_logger


def _clear_logger(name):
    """Helper to reset a named logger back to a clean, handler-less state so
    setup_logger()'s `if not logger.handlers` guard can be exercised freshly."""
    lg = logging.getLogger(name)
    lg.handlers.clear()
    return lg


def test_setup_logger_returns_configured_logger():
    name = "test_logger_configured"
    _clear_logger(name)

    result = setup_logger(name)

    assert isinstance(result, logging.Logger)
    assert result.name == name
    assert result.level == logging.INFO


def test_setup_logger_attaches_stream_handler_with_json_formatter():
    name = "test_logger_handler"
    _clear_logger(name)

    result = setup_logger(name)

    assert len(result.handlers) == 1
    handler = result.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stdout
    assert isinstance(handler.formatter, jsonlogger.JsonFormatter)


def test_setup_logger_default_name():
    # Calling with no args should use the default name used by the module-level singleton.
    result = setup_logger()
    assert result.name == "nego_lah_backend"


def test_setup_logger_does_not_duplicate_handlers_on_repeat_calls():
    name = "test_logger_no_dup"
    _clear_logger(name)

    first = setup_logger(name)
    assert len(first.handlers) == 1

    second = setup_logger(name)
    assert second is first
    # Guarded by `if not logger.handlers`, so calling again must not add more handlers.
    assert len(second.handlers) == 1


def test_setup_logger_returns_same_underlying_logger_for_same_name():
    name = "test_logger_identity"
    _clear_logger(name)

    a = setup_logger(name)
    b = setup_logger(name)

    assert a is b
    assert a is logging.getLogger(name)


def test_setup_logger_distinct_names_are_independent():
    name_a = "test_logger_a"
    name_b = "test_logger_b"
    _clear_logger(name_a)
    _clear_logger(name_b)

    logger_a = setup_logger(name_a)
    logger_b = setup_logger(name_b)

    assert logger_a is not logger_b
    assert logger_a.name != logger_b.name


def test_module_level_logger_singleton_is_configured():
    assert isinstance(module_logger, logging.Logger)
    assert module_logger.name == "nego_lah_backend"
    assert module_logger.level == logging.INFO
    assert len(module_logger.handlers) >= 1
    assert isinstance(module_logger.handlers[0], logging.StreamHandler)


def test_module_level_logger_can_log_without_raising():
    # Exercise info/warning/error/exception code paths through the real JSON formatter.
    module_logger.info("info message from test")
    module_logger.warning("warning message from test")
    module_logger.error("error message from test")

    try:
        raise ValueError("boom")
    except ValueError:
        module_logger.exception("exception message from test")


def test_json_formatter_produces_valid_json_output():
    import io
    import json

    name = "test_logger_json_output"
    _clear_logger(name)
    lg = setup_logger(name)

    stream = io.StringIO()
    # Swap out the handler's stream so we can capture and inspect the emitted record.
    lg.handlers[0].stream = stream

    lg.info("hello world")

    output = stream.getvalue().strip()
    assert output  # something was written
    parsed = json.loads(output)
    assert parsed["message"] == "hello world"
    assert parsed["levelname"] == "INFO"
    assert parsed["name"] == name
    assert "asctime" in parsed
