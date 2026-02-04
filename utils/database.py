import os
import mysql.connector
from .logger import log

class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            try:
                cls._instance.connection = cls._instance._get_db_connection()
                cls._instance.setup_database()
                log.info("Database connection successful and setup complete.")
            except mysql.connector.Error as err:
                log.critical(f"Database connection failed: {err}")
                raise  # Re-raise the exception to be caught by the caller
        return cls._instance

    def _get_db_connection(self):
        """
        Establishes a connection to the MySQL database.
        Raises mysql.connector.Error on failure.
        """
        port = os.getenv("DATABASE_PORT")
        if not port:
            log.error("DATABASE_PORT environment variable is not set.")
            raise ValueError("DATABASE_PORT is not set")
            
        return mysql.connector.connect(
            host=os.getenv("DATABASE_HOST"),
            port=port,
            user=os.getenv("DATABASE_USER"),
            password=os.getenv("DATABASE_PASSWORD"),
            database=os.getenv("DATABASE_DATABASE")
        )

    def _ensure_connection(self):
        """Ensures the database connection is active, reconnecting if necessary."""
        try:
            if not self.connection or not self.connection.is_connected():
                log.warning("Database connection lost. Reconnecting...")
                self.connection = self._get_db_connection()
        except mysql.connector.Error as err:
            log.error(f"Database connection check failed. Reconnecting... Error: {err}")
            try:
                self.connection = self._get_db_connection()
            except mysql.connector.Error as e:
                log.critical(f"Failed to re-establish database connection: {e}")
                return False
        
        if not self.connection or not self.connection.is_connected():
            log.critical("Failed to establish a database connection.")
            return False
        return True

    def setup_database(self):
        """
        Ensures the tables and columns exist in the database.
        """
        if not self._ensure_connection():
            raise mysql.connector.Error("Cannot set up database without a connection.")

        cursor = self.connection.cursor()
        
        # Create tables if they don't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) UNIQUE,
                price FLOAT,
                description TEXT,
                image_url VARCHAR(255),
                quantity INT,
                message_id BIGINT,
                channel_id BIGINT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS carts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT,
                channel_id BIGINT,
                cart_data JSON,
                message_id BIGINT,
                invoice_message_id BIGINT,
                payment_id VARCHAR(255),
                credit_applied FLOAT DEFAULT 0,
                last_activity DATETIME,
                status VARCHAR(255) DEFAULT 'active',
                payment_method VARCHAR(50) DEFAULT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                balance FLOAT DEFAULT 0,
                lifetime_spent FLOAT DEFAULT 0,
                delivery_value_handled DECIMAL(10, 2) DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_tiers (
                role_id BIGINT PRIMARY KEY,
                amount_required FLOAT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INT AUTO_INCREMENT PRIMARY KEY,
                message_id BIGINT,
                end_time DATETIME,
                status VARCHAR(50) DEFAULT 'active'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_entrants (
                giveaway_id INT,
                user_id BIGINT,
                PRIMARY KEY (giveaway_id, user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT,
                channel_id BIGINT,
                status VARCHAR(255) DEFAULT 'open'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                setting_name VARCHAR(255) PRIMARY KEY,
                setting_value TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analytics (
                id INT AUTO_INCREMENT PRIMARY KEY,
                event_type VARCHAR(255),
                item_id INT,
                user_id BIGINT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Add missing columns
        cursor.execute("SHOW COLUMNS FROM carts LIKE 'payment_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE carts ADD COLUMN payment_id VARCHAR(255)")
        
        cursor.execute("SHOW COLUMNS FROM carts LIKE 'credit_applied'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE carts ADD COLUMN credit_applied FLOAT DEFAULT 0")

        cursor.execute("SHOW COLUMNS FROM users LIKE 'lifetime_spent'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN lifetime_spent FLOAT DEFAULT 0")

        cursor.execute("SHOW COLUMNS FROM users LIKE 'delivery_value_handled'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN delivery_value_handled DECIMAL(10, 2) DEFAULT 0")

        cursor.execute("SHOW COLUMNS FROM carts LIKE 'payment_method'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE carts ADD COLUMN payment_method VARCHAR(50) DEFAULT NULL")
        
        cursor.execute("SHOW COLUMNS FROM giveaways LIKE 'status'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE giveaways ADD COLUMN status VARCHAR(50) DEFAULT 'active'")

        # Insert default settings if they don't exist
        cursor.execute("INSERT IGNORE INTO settings (setting_name, setting_value) VALUES (%s, %s)", ('shop_status', 'open'))
        cursor.execute("INSERT IGNORE INTO settings (setting_name, setting_value) VALUES (%s, %s)", ('hide_stock', 'false'))
        cursor.execute("INSERT IGNORE INTO settings (setting_name, setting_value) VALUES (%s, %s)", ('shop_status_channel_id', '0'))


        self.connection.commit()
        cursor.close()
        log.info("Database schema verified and updated.")

    def execute_query(self, query, params=None, fetch=None):
        if not self._ensure_connection():
            return None

        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(query, params)
            
            if fetch == 'one':
                result = cursor.fetchone()
            elif fetch == 'all':
                result = cursor.fetchall()
            else:
                result = None
            
            last_id = None
            if query.strip().upper().startswith('INSERT'):
                last_id = cursor.lastrowid

            self.connection.commit()
            cursor.close()

            if last_id is not None:
                return last_id
                
            return result
        except mysql.connector.Error as err:
            log.error(f"Database query error: {err}", exc_info=True)
            return None

    def get_setting(self, setting_name: str):
        """Retrieves a setting value from the database."""
        result = self.execute_query("SELECT setting_value FROM settings WHERE setting_name = %s", (setting_name,), fetch='one')
        return result['setting_value'] if result else None

    def set_setting(self, setting_name: str, setting_value: str):
        """Sets a setting value in the database."""
        self.execute_query("INSERT INTO settings (setting_name, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = %s", (setting_name, setting_value, setting_value))
