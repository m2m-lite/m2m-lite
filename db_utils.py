"""Database utilities for m2m-lite."""

import sqlite3

from log_utils import get_logger

logger = get_logger("db_utils")


# Initialize SQLite database
def initialize_database():
    """
    Initialize the SQLite database and create tables if they don't exist.
    """
    try:
        with sqlite3.connect("meshtastic.sqlite") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS longnames (meshtastic_id TEXT PRIMARY KEY, longname TEXT)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS shortnames (meshtastic_id TEXT PRIMARY KEY, shortname TEXT)"
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error initializing database: {e}")


# Get the longname for a given Meshtastic ID
def get_longname(meshtastic_id):
    """
    Get the longname for a given Meshtastic ID.

    :param meshtastic_id: The Meshtastic ID.
    :return: The longname, or None if not found.
    """
    try:
        with sqlite3.connect("meshtastic.sqlite") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT longname FROM longnames WHERE meshtastic_id=?", (meshtastic_id,)
            )
            result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        logger.error(f"Error getting longname for {meshtastic_id}: {e}")
        return None


# Get the shortname for a given Meshtastic ID
def get_shortname(meshtastic_id):
    """
    Get the shortname for a given Meshtastic ID.

    :param meshtastic_id: The Meshtastic ID.
    :return: The shortname, or None if not found.
    """
    try:
        with sqlite3.connect("meshtastic.sqlite") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT shortname FROM shortnames WHERE meshtastic_id=?",
                (meshtastic_id,),
            )
            result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        logger.error(f"Error getting shortname for {meshtastic_id}: {e}")
        return None


# Save the longname for a given Meshtastic ID
def save_longname(meshtastic_id, longname):
    """
    Save the longname for a given Meshtastic ID.

    :param meshtastic_id: The Meshtastic ID.
    :param longname: The longname.
    """
    try:
        with sqlite3.connect("meshtastic.sqlite") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO longnames (meshtastic_id, longname) VALUES (?, ?)",
                (meshtastic_id, longname),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error saving longname for {meshtastic_id}: {e}")


# Save the shortname for a given Meshtastic ID
def save_shortname(meshtastic_id, shortname):
    """
    Save the shortname for a given Meshtastic ID.

    :param meshtastic_id: The Meshtastic ID.
    :param shortname: The shortname.
    """
    try:
        with sqlite3.connect("meshtastic.sqlite") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO shortnames (meshtastic_id, shortname) VALUES (?, ?)",
                (meshtastic_id, shortname),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error saving shortname for {meshtastic_id}: {e}")
