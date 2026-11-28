"""Database helper: connects the Flask app to the Supabase Postgres database.

How it works:
- The connection string is read from .env (DATABASE_URL). It is never
  printed, logged, or written in the code.
- Each request gets at most one connection, stored on Flask's `g`
  (a place to keep things for the current request only).
- When the request ends, the connection is committed (or rolled back if
  something went wrong) and closed.
- Rows come back as dictionaries, e.g. {"id": "...", "month": "2026-11"}.

Always pass values with %s placeholders, never with f-strings:
    query("select * from budgets where user_id = %s", (auth.current_user_id(),))
psycopg sends the values separately from the SQL, so they can't change
what the query does (this prevents SQL injection).
"""
import os

import psycopg
from dotenv import load_dotenv
from flask import g
from psycopg.rows import dict_row

# Read the variables in .env into the environment
load_dotenv()

# The logged-in user's ID comes from auth.current_user_id().
#
# DEV_USER_ID owns the sample data that seed.py copies into the database.
# It isn't a real account, so nobody can log in as this user.
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


class DatabaseConfigError(Exception):
    """DATABASE_URL is missing or isn't a Postgres connection string."""


def _connection_string():
    """Get the connection string from the environment, checking its shape."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise DatabaseConfigError("DATABASE_URL is not set in .env.")
    if not url.startswith(("postgresql://", "postgres://")):
        # A common mix-up: the https:// project URL instead of the database one
        raise DatabaseConfigError(
            "DATABASE_URL must be a Postgres connection string starting with "
            "postgresql:// (Supabase: Connect > Connection string), "
            "not the https:// project URL."
        )
    return url


def connect():
    """Open a new database connection. Used by get_db() and by seed.py."""
    return psycopg.connect(
        _connection_string(),
        row_factory=dict_row,   # rows come back as dictionaries
        prepare_threshold=None, # needed for Supabase's connection pooler
        connect_timeout=10,     # give up after 10 seconds instead of hanging
    )


def get_db():
    """Return this request's database connection, opening it the first time."""
    if "db" not in g:
        g.db = connect()
    return g.db


def query(sql, params=(), one=False):
    """Run a SQL query and return its rows (or just the first row if one=True).

    Example:
        query("select count(*) as n from budgets where user_id = %s",
              (auth.current_user_id(),), one=True)
    """
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:  # e.g. an insert/update with no rows returned
            return None
        return cur.fetchone() if one else cur.fetchall()


def close_db(error=None):
    """At the end of each request: save changes (or undo them on error), then close."""
    db = g.pop("db", None)
    if db is None:
        return  # this request never used the database
    try:
        if error is None:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()


def init_app(app):
    """Tell Flask to call close_db() after every request."""
    app.teardown_appcontext(close_db)
