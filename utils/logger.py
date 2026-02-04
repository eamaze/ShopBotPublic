import logging
import coloredlogs
import os

def setup_logging():
    """
    Sets up a centralized logger with colored console output and file logging.
    """
    # Create a logger object
    logger = logging.getLogger('ShopBot')
    logger.setLevel(logging.INFO)

    # Prevent the root logger from handling messages
    logger.propagate = False

    # Define the log format
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # --- Console Handler with Colors ---
    # Remove any existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # Define color styles
    field_styles = coloredlogs.DEFAULT_FIELD_STYLES
    level_styles = {
        'info': {'color': 'white'},
        'warning': {'color': 'yellow'},
        'error': {'color': 'red'},
        'critical': {'color': 'red', 'bold': True}
    }
    
    # Install coloredlogs
    coloredlogs.install(
        level='INFO',
        logger=logger,
        fmt=log_format,
        field_styles=field_styles,
        level_styles=level_styles
    )

    # --- File Handler ---
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    file_handler = logging.FileHandler(os.path.join(log_dir, 'shopbot.log'), mode='a')
    file_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(file_handler)
    
    return logger

# Create a logger instance to be imported by other modules
log = setup_logging()
