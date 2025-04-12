import logging
import sys

# === Logging setup ===
LOG_FILE = "logs/app.log"

# Create a custom logger
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

# File handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)

# Console handler (optional)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

# Add handlers
logger.handlers = []  # Clear existing
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Redirect print() to logger
class StreamToLogger:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def write(self, message):
        message = message.strip()
        if message:
            self.logger.log(self.level, message)

    def flush(self):
        pass
        
    def reconfigure(self, *args, **kwargs):
        # Added to handle reconfigure calls that might come from libraries
        pass

sys.stdout = StreamToLogger(logger, logging.INFO)
sys.stderr = StreamToLogger(logger, logging.ERROR)