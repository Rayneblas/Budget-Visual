"""Login with email and password, using Supabase Auth.

How it works:
- Supabase stores the accounts and checks the passwords. Flask never
  stores a password anywhere.
- To sign up or log in, Flask asks Supabase using the "supabase" package
  and the publishable key.
- If Supabase says yes, Flask saves only the user's id and email in the
  session: a cookie that Flask signs with SECRET_KEY, so it can't be
  faked or edited in the browser.
- Routes marked with @login_required can only be used when logged in.

Settings come from .env:
    SUPABASE_URL   https://<project>.supabase.co
    SUPABASE_KEY   the publishable key (sb_publishable_...)
    SECRET_KEY     random text used to sign the session cookie
    APP_ENV        set to "production" when the site runs on HTTPS
"""
import os
import re
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import jsonify, redirect, request, session, url_for
from supabase import AuthApiError, create_client

load_dotenv()

# Every JSON route lives under /budgets. When one of those is used without
# logging in, it gets a 401 error instead of a redirect to the login page.
API_PREFIX = "/budgets"

# Friendly messages for the error codes Supabase sends back
FRIENDLY_ERRORS = {
    "invalid_credentials": "Incorrect email or password.",
    "user_already_exists": "An account with this email already exists.",
    "email_exists": "An account with this email already exists.",
    "weak_password": "That password is too weak. Try a longer one with a mix of letters and numbers.",
    "email_address_invalid": "Enter a valid email address.",
    "email_not_confirmed": "Please confirm your email first. Check your inbox for the link.",
    "over_request_rate_limit": "Too many attempts. Wait a minute and try again.",
    "over_email_send_rate_limit": "Too many emails were sent. Wait a while and try again.",
    "signup_disabled": "New sign-ups are turned off right now.",
}


class LoginError(Exception):
    """Signing up or logging in failed. The message is safe to show on the page."""


# ---------- Talking to Supabase ----------

def new_supabase_client():
    """Make a brand-new Supabase client.

    A client remembers whoever last logged in with it. If the whole app
    shared one client, two people logging in at the same time could get
    mixed up, so every sign-up and log-in gets its own client.
    """
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url.startswith("https://") or not key:
        raise LoginError("Login isn't set up yet: add SUPABASE_URL (https://...) and SUPABASE_KEY to .env.")
    # Keep only "https://<project>.supabase.co". Supabase's dashboard also shows
    # addresses ending in /rest/v1/, and with that on the end, login requests
    # go to the wrong place.
    parts = urlsplit(url)
    return create_client(f"{parts.scheme}://{parts.netloc}", key)


def friendly_message(error):
    """Turn a Supabase error into a message for the page (never the raw error)."""
    return FRIENDLY_ERRORS.get(getattr(error, "code", None), "Something went wrong. Please try again.")


def sign_up(email, password):
    """Create an account.

    Returns the user ({"id", "email"}) when they're logged in right away.
    Returns None if Supabase wants them to confirm their email first
    (only happens if "Confirm email" is turned on in Supabase).
    """
    client = new_supabase_client()  # outside "try", so a setup problem shows its own message
    try:
        result = client.auth.sign_up({"email": email, "password": password})
    except AuthApiError as e:
        raise LoginError(friendly_message(e))
    except Exception:
        # e.g. no internet connection. The raw error isn't shown on the page.
        raise LoginError("Couldn't reach the login service. Check your connection and try again.")

    if result.session is None:
        return None
    return {"id": result.user.id, "email": result.user.email}


def log_in(email, password):
    """Check an email and password. Returns the user ({"id", "email"})."""
    client = new_supabase_client()  # outside "try", so a setup problem shows its own message
    try:
        result = client.auth.sign_in_with_password({"email": email, "password": password})
    except AuthApiError as e:
        raise LoginError(friendly_message(e))
    except Exception:
        raise LoginError("Couldn't reach the login service. Check your connection and try again.")
    return {"id": result.user.id, "email": result.user.email}


# ---------- Checking what people typed ----------

# Something@something.something, with no spaces. (Supabase checks it again.)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def signup_problem(email, password, confirm):
    """The first thing wrong with a sign-up form, or None if it's all OK."""
    if not EMAIL_PATTERN.match(email):
        return "Enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password != confirm:
        return "The passwords don't match."
    return None


# ---------- Remembering who's logged in ----------

def remember_user(user):
    """Save the logged-in user in the session cookie: only their id and email."""
    session.clear()            # start fresh, so nothing from before carries over
    session.permanent = True   # keep them logged in for PERMANENT_SESSION_LIFETIME
    session["user_id"] = user["id"]
    session["email"] = user["email"]


def forget_user():
    """Log out: empty the session cookie."""
    session.clear()


def current_user_id():
    """The logged-in user's id (a UUID string), or None if nobody is logged in."""
    return session.get("user_id")


def safe_next(url):
    """Where to go after logging in: `url` if it's a page on this site, else home.

    Only paths like "/month/2026-11" are allowed. Something like
    "https://evil.example" or "//evil.example" would send people to another
    site after they log in (an "open redirect"), so those go home instead.
    """
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return url_for("home")


def login_required(view):
    """Put @login_required above a route so only logged-in users can use it.

    Pages send logged-out visitors to /login?next=<the page they wanted>.
    JSON routes (under /budgets) reply with a 401 error instead.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user_id():
            return view(*args, **kwargs)
        if request.path.startswith(API_PREFIX):
            return jsonify({"error": "Not logged in"}), 401
        return redirect(url_for("login", next=request.full_path.rstrip("?")))
    return wrapper


# ---------- Hooking it into Flask ----------

def init_app(app):
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY is missing from .env (needed to sign login cookies).")
    app.secret_key = secret

    app.config.update(
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),  # stay logged in for a week
        SESSION_COOKIE_HTTPONLY=True,    # JavaScript in the page can't read the cookie
        SESSION_COOKIE_SAMESITE="Lax",   # other sites can't submit forms with it
        # Secure = only send the cookie over HTTPS. Only in production, because
        # http://localhost isn't HTTPS and login would stop working there.
        SESSION_COOKIE_SECURE=os.environ.get("APP_ENV") == "production",
    )

    @app.context_processor
    def add_user_to_templates():
        """Lets every template use {{ current_email }} (None when logged out)."""
        return {"current_email": session.get("email")}
