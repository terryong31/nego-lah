import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_logger(name="nego_lah_backend"):
    logger = logging.getLogger(name)
    
    # Only configure if no handlers exist to prevent duplicate logs in case of reload
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        logHandler = logging.StreamHandler(sys.stdout)
        
        # Format the log output as JSON
        # This includes standard logging fields like timestamp, level, name, and message
        formatter = jsonlogger.JsonFormatter(
            '%(asctime)s %(levelname)s %(name)s %(message)s'
        )
        
        logHandler.setFormatter(formatter)
        logger.addHandler(logHandler)
        
    return logger

# Global logger instance
logger = setup_logger()
