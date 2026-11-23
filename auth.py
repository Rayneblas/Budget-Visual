"""Login with email and password, using Supabase Auth.

How it works:
- Supabase stores the users and checks their passwords. Flask never
  stores a password anywhere.
- Flask sends the email and password to Supabase's Auth API. If Supabase
  says they're correct, Flask saves the user's ID and email in the
  session: a cookie that Flask signs with FLASK_SECRET_KEY, so it
  can't be faked or edited in the browser.
- Every page except the login pages requires a logged-in user.

Settings come from .env:
    SUPABASE_PROJECT_URL  https://<project>.supabase.co
    SUPABASE_SECRET_KEY   server-only key (never send it to the browser)
    FLASK_SECRET_KEY      random text used to sign the session cookie
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from dotenv import load_dotenv
from flask import jsonify, redirect, request, session, url_for

load_dotenv()

# TEMPORARY: login is switched off so every page opens without logging in.
# Set this back to True to require login again.
LOGIN_REQUIRED = False

# Pages anyone can open without logging in (Flask "endpoint" names, which are
# the route function names)
PUBLIC_ENDPOINTS = {"login", "signup", "logout", "static"}

# Friendly messages for the error codes Supabase sends back
FRIENDLY_ERRORS = {
    "invalid_credentials": "That email and password don't match. Try again.",
    "email_not_confirmed": "Please confirm your email first. Check your inbox for the link.",
    "user_already_exists": "There's already an account with that email. Try logging in.",
    "email_exists": "There's already an account with that email. Try logging in.",
    "weak_password": "That password is too weak. Use at least 6 characters.",
    "email_address_invalid": "That doesn't look like a valid email address.",
    "validation_failed": "Check the email and password and try again.",
    "over_email_send_rate_limit": "Too many sign-up emails were sent. Wait a while and try again.",
    "over_request_rate_limit": "Too many attempts. Wait a minute and try again.",
    "signup_disabled": "New sign-ups are turned off right now.",
}


class AuthError(Exception):
    """Something went wrong logging in or signing up. The message is safe to show."""


# ---------- Talking to Supabase ----------

def _supabase_auth(path, payload):
    """POST JSON to Supabase's Auth API and return the JSON reply.

    Raises AuthError with a friendly message if Supabase says no.
    """
    base_url = os.environ.get("SUPABASE_PROJECT_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY", "")
    if not base_url or not key:
        raise AuthError("Login isn't set up: SUPABASE_PROJECT_URL or SUPABASE_SECRET_KEY is missing from .env.")

    req = urllib.request.Request(
        f"{base_url}/auth/v1/{path}",
        data=json.dumps(payload).encode(),
        headers={"apikey": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        # Supabase said no: turn its error code into a friendly message
        try:
            body = json.load(e)
        except ValueError:
            body = {}
        code = body.get("error_code") or body.get("error")
        message = body.get("msg") or body.get("error_description")
        raise AuthError(FRIENDLY_ERRORS.get(code) or message or "Something went wrong. Please try again.")
    except (urllib.error.URLError, TimeoutError):
        raise AuthError("Couldn't reach the login service. Check your internet connection and try again.")


def sign_up(email, password, confirm_url):
    """Create an account.

    Returns the user ({"id", "email"}) if they're logged in right away, or
    None if Supabase sent a confirmation email first (the usual case).
    confirm_url is where the link in that email sends them afterwards.
    """
    data = _supabase_auth(f"signup?redirect_to={urllib.parse.quote(confirm_url)}",
                          {"email": email, "password": password})
    # With email confirmation on, Supabase replies without an access_token
    if "access_token" in data:
        return {"id": data["user"]["id"], "email": data["user"]["email"]}
    return None


def log_in(email, password):
    """Check an email and password. Returns the user ({"id", "email"})."""
    data = _supabase_auth("token?grant_type=password", {"email": email, "password": password})
    return {"id": data["user"]["id"], "email": data["user"]["email"]}


# ---------- Remembering who's logged in ----------

def remember_user(user):
    """Save the logged-in user in the session cookie."""
    session.clear()            # start fresh, so nothing from before carries over
    session.permanent = True   # stay logged in for PERMANENT_SESSION_LIFETIME
    session["user_id"] = user["id"]
    session["email"] = user["email"]


def forget_user():
    """Log out: empty the session cookie."""
    session.clear()


def current_user_id():
    """The logged-in user's ID (a UUID string), or None.

    This replaces Phase 1's DEV_USER_ID placeholder.
    """
    return session.get("user_id")


def is_safe_next(url):
    """Only allow redirects to pages on this site (e.g. "/month/2026-11").

    Stops a link like /login?next=https://evil.example from sending
    people to another site after they log in.
    """
    return bool(url) and url.startswith("/") and not url.startswith("//") and "\\" not in url


# ---------- Hooking it into Flask ----------

def init_app(app):
    secret = os.environ.get("FLASK_SECRET_KEY")
    if not secret:
        raise RuntimeError("FLASK_SECRET_KEY is missing from .env (needed to sign login cookies).")
    app.secret_key = secret
    app.config.update(
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),  # stay logged in for a week
        SESSION_COOKIE_HTTPONLY=True,   # JavaScript can't read the cookie
        SESSION_COOKIE_SAMESITE="Lax",  # other sites can't send forms using it
    )

    @app.before_request
    def require_login():
        """Runs before every request: send logged-out visitors to the login page."""
        if not LOGIN_REQUIRED:
            return None  # login is switched off (see LOGIN_REQUIRED above)
        if request.endpoint in PUBLIC_ENDPOINTS or current_user_id():
            return None  # allowed: carry on to the page
        # Data routes (used by the pages' JavaScript) get an error instead of a page
        if request.path.startswith("/budgets"):
            return jsonify({"error": "Please log in."}), 401
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    @app.context_processor
    def add_user_to_templates():
        """Lets every template use {{ current_email }} (None when logged out)."""
        return {"current_email": session.get("email")}
