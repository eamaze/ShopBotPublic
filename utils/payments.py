import os
import base64
from abc import ABC, abstractmethod
import requests
from .logger import log
import time
from typing import Optional

class PaymentMethod(ABC):
    """Abstract base class for all payment methods."""
    @abstractmethod
    def create_payment(self, total_price: float, items: list, description: str, return_url: str, cancel_url: str, cart_id: int):
        pass

    @abstractmethod
    def get_payment_details(self, payment_id: str, cart_id: Optional[int] = None): # Added cart_id
        pass

class PayPalPayment(PaymentMethod):
    """Concrete implementation of PaymentMethod for PayPal using the v2 API."""
    def __init__(self):
        self.mode = os.getenv("PAYPAL_MODE", "sandbox")
        self.base_url = "https://api-m.sandbox.paypal.com" if self.mode == "sandbox" else "https://api-m.paypal.com"
        
        if self.mode == "sandbox":
            self.client_id = os.getenv("PAYPAL_SANDBOX_CLIENT_ID")
            self.client_secret = os.getenv("PAYPAL_SANDBOX_CLIENT_SECRET")
        else:
            self.client_id = os.getenv("PAYPAL_LIVE_CLIENT_ID")
            self.client_secret = os.getenv("PAYPAL_LIVE_CLIENT_SECRET")

        self._access_token = None
        self._token_expires_at = 0
        
        if not self.client_id or not self.client_secret:
            log.error(f"PayPal {self.mode.capitalize()} credentials not found. Check your environment variables.")
        else:
            log.info(f"PayPalPayment (v2) initialized in {self.mode} mode.")

    def _get_access_token(self):
        """Fetches or renews the PayPal API access token."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        log.info("Fetching new PayPal access token...")
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}
        data = {"grant_type": "client_credentials"}
        
        try:
            response = requests.post(f"{self.base_url}/v1/oauth2/token", headers=headers, data=data)
            response.raise_for_status()
            token_data = response.json()
            self._access_token = token_data["access_token"]
            self._token_expires_at = time.time() + token_data["expires_in"] - 300  # Refresh 5 mins before expiry
            log.info("Successfully fetched PayPal access token.")
            return self._access_token
        except requests.exceptions.RequestException as e:
            log.error(f"Failed to get PayPal access token: {e}", exc_info=True)
            if 'response' in locals() and hasattr(response, 'text'):
                log.error(f"PayPal API Response: {response.text}")
            return None

    def create_payment(self, total_price: float, items: list, description: str, return_url: str, cancel_url: str, cart_id: int):
        """Creates a PayPal order and returns the approval URL and order ID."""
        access_token = self._get_access_token()
        if not access_token:
            return None, None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        
        purchase_units = [{
            "amount": {
                "currency_code": "USD",
                "value": f"{total_price:.2f}",
                "breakdown": {
                    "item_total": {
                        "currency_code": "USD",
                        "value": f"{total_price:.2f}"
                    }
                }
            },
            "items": items,
            "custom_id": str(cart_id)
        }]

        payload = {
            "intent": "CAPTURE",
            "purchase_units": purchase_units,
            "application_context": {
                "return_url": return_url,
                "cancel_url": cancel_url,
                "brand_name": "2b2t Store",
                "landing_page": "BILLING",
                "user_action": "PAY_NOW"
            }
        }

        try:
            response = requests.post(f"{self.base_url}/v2/checkout/orders", headers=headers, json=payload)
            response.raise_for_status()
            order_data = response.json()
            approval_link = next(link['href'] for link in order_data['links'] if link['rel'] == 'approve')
            log.info(f"Created PayPal Order {order_data['id']} for cart {cart_id}.")
            return approval_link, order_data['id']
        except (requests.exceptions.RequestException, StopIteration, KeyError) as e:
            log.error(f"Failed to create PayPal order: {e}", exc_info=True)
            if 'response' in locals():
                log.error(f"PayPal API Response: {response.text}")
            return None, None

    def get_payment_details(self, payment_id: str, cart_id: Optional[int] = None):
        """Retrieves order details from PayPal."""
        access_token = self._get_access_token()
        if not access_token:
            return None

        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = requests.get(f"{self.base_url}/v2/checkout/orders/{payment_id}", headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            log.error(f"Failed to get PayPal order details for {payment_id}: {e}", exc_info=True)
            return None

    def capture_payment(self, order_id: str):
        """Captures a payment for an approved order."""
        access_token = self._get_access_token()
        if not access_token:
            return None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        
        try:
            # The capture endpoint requires an empty JSON body {}
            response = requests.post(f"{self.base_url}/v2/checkout/orders/{order_id}/capture", headers=headers, json={})
            response.raise_for_status()
            capture_data = response.json()
            log.info(f"Successfully captured PayPal payment for order {order_id}.")
            return capture_data
        except requests.exceptions.RequestException as e:
            log.error(f"Failed to capture PayPal payment for order {order_id}: {e}", exc_info=True)
            if 'response' in locals():
                log.error(f"PayPal API Response: {response.text}")
            return None

class CryptoPayment(PaymentMethod):
    """
    Handles cryptocurrency payments by providing wallet addresses and verifying payments.
    """
    def __init__(self):
        # In a real application, you would load wallet addresses from a secure config
        self.wallet_addresses = {
            "BTC": os.getenv("CRYPTO_BTC"),
            "ETH": os.getenv("CRYPTO_ETH"),
            "LTC": os.getenv("CRYPTO_LTC"),
        }
        self.api_url = "https://api.coingecko.com/api/v3"
        log.info("CryptoPayment initialized.")

    def create_payment(self, total_price: float, items: list, description: str, return_url: str, cancel_url: str, cart_id: int):
        # This method will now return the necessary information for the user to make a payment.
        # It won't create a transaction on a third-party service.
        # The 'payment_id' can be the cart_id for tracking purposes.
        return "crypto_payment_info", str(cart_id)

    def get_payment_details(self, payment_id: str, cart_id: Optional[int] = None):
        # This method will be used to check if the payment has been made.
        # For now, it will return a placeholder.
        return {"status": "pending"}

    def get_coin_price(self, coin_id: str) -> Optional[float]:
        """
        Gets the current price of a cryptocurrency in USD from CoinGecko.
        """
        try:
            response = requests.get(f"{self.api_url}/simple/price", params={"ids": coin_id, "vs_currencies": "usd"})
            response.raise_for_status()
            data = response.json()
            return data[coin_id]["usd"]
        except requests.exceptions.RequestException as e:
            log.error(f"Could not fetch price for {coin_id}: {e}")
            return None
