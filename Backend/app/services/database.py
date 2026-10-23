"""Database readiness checks used before starting the HTTP server."""

import logging

import mysql.connector

logger = logging.getLogger(__name__)


class DatabaseStartupError(RuntimeError):
    """The application database is unavailable during startup."""


def verify_database_connection(config):
    """Open and close a MySQL connection before the app begins serving requests."""
    connection = None
    cursor = None
    try:
        connection = mysql.connector.connect(
            host=config["DB_HOST"],
            port=config["DB_PORT"],
            user=config["DB_USER"],
            password=config["DB_PASSWORD"],
            database=config["DB_NAME"],
            connection_timeout=10,
        )
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        if not result or result[0] != 1:
            raise DatabaseStartupError("MySQL readiness check returned an unexpected result.")
    except DatabaseStartupError:
        raise
    except mysql.connector.Error as error:
        logger.exception("MySQL startup connection check failed")
        raise DatabaseStartupError(
            f"Could not connect to MySQL database '{config['DB_NAME']}' "
            f"at {config['DB_HOST']}:{config['DB_PORT']}: {error}"
        ) from error
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except mysql.connector.Error:
                logger.exception("Could not close MySQL startup-check cursor")
        if connection is not None:
            try:
                connection.close()
            except mysql.connector.Error:
                logger.exception("Could not close MySQL startup-check connection")
