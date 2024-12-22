import sqlite3

from log_utils import get_logger

logger = get_logger(name="db_utils")

# Initialize SQLite database
def initialize_database():
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        # Updated table schema: matrix_event_id is now PRIMARY KEY, meshtastic_id is not necessarily unique
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS longnames (meshtastic_id TEXT PRIMARY KEY, longname TEXT)"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS shortnames (meshtastic_id TEXT PRIMARY KEY, shortname TEXT)"
        )

        conn.commit()

# Get the longname for a given Meshtastic ID
def get_longname(meshtastic_id):
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT longname FROM longnames WHERE meshtastic_id=?", (meshtastic_id,)
        )
        result = cursor.fetchone()
    return result[0] if result else None

def save_longname(meshtastic_id, longname):
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO longnames (meshtastic_id, longname) VALUES (?, ?)",
            (meshtastic_id, longname),
        )
        conn.commit()

def update_longnames(nodes):
    if nodes:
        for node in nodes.values():
            user = node.get("user")
            if user:
                meshtastic_id = user["id"]
                longname = user.get("longName", "N/A")
                save_longname(meshtastic_id, longname)

def get_shortname(meshtastic_id):
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT shortname FROM shortnames WHERE meshtastic_id=?", (meshtastic_id,)
        )
        result = cursor.fetchone()
    return result[0] if result else None

def save_shortname(meshtastic_id, shortname):
    with sqlite3.connect("meshtastic.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO shortnames (meshtastic_id, shortname) VALUES (?, ?)",
            (meshtastic_id, shortname),
        )
        conn.commit()

def update_shortnames(nodes):
    if nodes:
        for node in nodes.values():
            user = node.get("user")
            if user:
                meshtastic_id = user["id"]
                shortname = user.get("shortName", "N/A")
                save_shortname(meshtastic_id, shortname)
