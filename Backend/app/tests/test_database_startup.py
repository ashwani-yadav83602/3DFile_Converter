import unittest
from unittest.mock import Mock, patch

from mysql.connector.errors import InterfaceError

from app.services.database import DatabaseStartupError, verify_database_connection


class DatabaseStartupTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "DB_HOST": "localhost",
            "DB_PORT": 3306,
            "DB_USER": "test-user",
            "DB_PASSWORD": "test-password",
            "DB_NAME": "PLM",
        }

    def test_successful_connection_is_verified_and_closed(self):
        cursor = Mock()
        cursor.fetchone.return_value = (1,)
        connection = Mock()
        connection.cursor.return_value = cursor

        with patch(
            "app.services.database.mysql.connector.connect",
            return_value=connection,
        ) as connect:
            verify_database_connection(self.config)

        connect.assert_called_once_with(
            host="localhost",
            port=3306,
            user="test-user",
            password="test-password",
            database="PLM",
            connection_timeout=10,
        )
        cursor.execute.assert_called_once_with("SELECT 1")
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_connection_failure_raises_startup_error(self):
        with patch(
            "app.services.database.mysql.connector.connect",
            side_effect=InterfaceError("database unavailable"),
        ):
            with self.assertRaisesRegex(
                DatabaseStartupError, "Could not connect to MySQL database 'PLM'"
            ):
                verify_database_connection(self.config)

    def test_failed_readiness_query_still_closes_resources(self):
        cursor = Mock()
        cursor.fetchone.return_value = (0,)
        connection = Mock()
        connection.cursor.return_value = cursor

        with patch(
            "app.services.database.mysql.connector.connect",
            return_value=connection,
        ):
            with self.assertRaises(DatabaseStartupError):
                verify_database_connection(self.config)

        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()
