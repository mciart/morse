"""Per-process diagnostics, installed by the executable rather than on import."""

import faulthandler
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import sys


_fault_stream = None


def install_diagnostics(data_directory):
    global _fault_stream
    directory = Path(data_directory) / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    process_id = os.getpid()
    log_path = directory / f'morsewriter-{process_id}.log'
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s pid=%(process)d thread=%(threadName)s %(name)s: %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    _fault_stream = (directory / f'crash-{process_id}.log').open('a', encoding='utf-8')
    _fault_stream.write(f'{datetime.now().astimezone().isoformat()} pid={process_id} Python {sys.version}\n')
    _fault_stream.flush()
    faulthandler.enable(file=_fault_stream, all_threads=True)
    original_hook = sys.excepthook

    def report_exception(kind, value, traceback):
        logging.critical('Unhandled Python exception', exc_info=(kind, value, traceback))
        original_hook(kind, value, traceback)

    sys.excepthook = report_exception
    logging.info('Application started: Python %s; %s', sys.version, platform.platform())
    return log_path


def log_qt_message(message_type, context, message):
    # Qt can invoke this from its audio thread; Python logging serializes writes.
    logging.getLogger('Qt').log(logging.WARNING if int(message_type) else logging.DEBUG,
                                '%s', message)
