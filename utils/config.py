import os
import json
import paypalrestsdk
from .logger import log  # Import the centralized logger

def setup_os():
    """
    Reads configuration from config.json and sets environment variables.
    """
    def set_env_vars(config_dict, prefix=''):
        for key, value in config_dict.items():
            new_key = f"{prefix.upper()}_{key.upper()}" if prefix else key.upper()
            if isinstance(value, dict):
                set_env_vars(value, new_key)
            else:
                os.environ[new_key] = str(value)

    try:
        # Construct the absolute path to config.json, assuming it's in the project root
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config.json'))
        with open(config_path, 'r') as f:
            config = json.load(f)
        set_env_vars(config)
        log.info("Environment variables set up successfully.")
    except FileNotFoundError:
        log.critical(f"Error: config.json not found at {config_path}")
        return False
    except json.JSONDecodeError:
        log.critical("Error: Could not decode config.json.")
        return False
    return True

def setup_paypal():
    """
    Configures the PayPal SDK.
    """
    mode = os.getenv("PAYPAL_MODE", "sandbox")
    if mode == "sandbox":
        log.warning("PayPal is running in sandbox mode.")
        client_id = os.getenv("PAYPAL_SANDBOX_CLIENT_ID")
        client_secret = os.getenv("PAYPAL_SANDBOX_CLIENT_SECRET")
    else:
        client_id = os.getenv("PAYPAL_LIVE_CLIENT_ID")
        client_secret = os.getenv("PAYPAL_LIVE_CLIENT_SECRET")

    paypalrestsdk.configure({
        "mode": mode,
        "client_id": client_id,
        "client_secret": client_secret
    })
    log.info("PayPal SDK configured.")
