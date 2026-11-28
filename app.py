import math
from datetime import date, datetime

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

import auth
import db

app = Flask(__name__)
db.init_app(app)    # closes each request's database connection when the request ends
auth.init_app(app)  # login cookies, and sends logged-out visitors to /login

def is_valid_month(month):
    """True if month looks like "2026-11" (a real year and month)."""
    try:
        datetime.strptime(month, "%Y-%m")
        return len(month) == 7
    except ValueError:
        return False


def text_of(value):
    """Turn a form value into trimmed text ("" if it's missing)."""
    return "" if value is None else str(value).strip()


def parse_money(text):
    """Turn text like "1,200.50" or "$900" into a number.

    Returns None if the text isn't a real number.
    """
    try:
        value = float(text.replace("$", "").replace(",", ""))
    except ValueError:
        return None
    # float() also accepts "inf" and "nan", which aren't real amounts
    return value if math.isfinite(value) else None


def validate_budget(data):
    """Check a submitted budget. Returns (errors, spending_limit, planned).

    errors is empty when everything is OK. Otherwise it looks like:
        {"spending_limit": "message",
         "categories": {"2": {"name": "message", "amount": "message"}}}
    where "2" is the row number (counting from 0). The setup page uses the
    same shape for its own checks, so it can show either kind inline.
    """
    errors = {}

    # ----- Spending limit: a number greater than 0 -----
    limit_text = text_of(data.get("spending_limit"))
    limit = parse_money(limit_text)
    if limit_text == "":
        errors["spending_limit"] = "Enter your monthly spending limit."
    elif limit is None:
        errors["spending_limit"] = "Enter a number, like 2000."
    elif limit <= 0:
        errors["spending_limit"] = "Your spending limit must be more than $0."

    # ----- Category rows -----
    rows = data.get("categories")
    if not isinstance(rows, list):
        rows = []

    planned = {}        # the clean result: {"Rent": 900.0, ...}
    row_errors = {}
    names_seen = set()  # lowercase names, to catch "Rent" and "rent"

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        name = text_of(row.get("name"))
        amount_text = text_of(row.get("amount"))

        # Completely empty rows are ignored
        if name == "" and amount_text == "":
            continue

        problems = {}
        amount = 0  # a named row with no amount is planned as $0
        if amount_text:
            amount = parse_money(amount_text)
            if amount is None:
                problems["amount"] = "Enter a number."
            elif amount < 0:
                problems["amount"] = "Amounts can't be negative."

        if name == "":
            problems["name"] = "Give this category a name."
        elif name.lower() in names_seen:
            problems["name"] = "You already have a category with this name."
        names_seen.add(name.lower())

        if problems:
            row_errors[str(i)] = problems
        else:
            planned[name] = round(amount, 2)

    if row_errors:
        errors["categories"] = row_errors

    return errors, limit, planned


# ---------- Login, sign up, log out ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log in with email and password."""
    if auth.current_user_id():
        return redirect(url_for("home"))  # already logged in

    # Where to go after logging in: the page they were trying to open,
    # but only if it's a page on this site (see auth.safe_next)
    next_page = auth.safe_next(request.values.get("next", ""))

    email = ""
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            error = "Enter your email and password."
        else:
            try:
                auth.remember_user(auth.log_in(email, password))
                return redirect(next_page)
            except auth.LoginError as e:
                error = str(e)

    # email is sent back so the field stays filled in after an error
    return render_template("login.html", mode="login", email=email, error=error, next_page=next_page)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Create an account with email, password and confirm password."""
    if auth.current_user_id():
        return redirect(url_for("home"))  # already logged in

    email = ""
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        # Check the form here first, then let Supabase create the account
        error = auth.signup_problem(email, password, confirm)
        if error is None:
            try:
                user = auth.sign_up(email, password)
                if user:
                    auth.remember_user(user)  # logged in right after signing up
                    return redirect(url_for("home"))
                # Only if "Confirm email" is still on in Supabase
                flash(f"Check your email: we sent a confirmation link to {email}. "
                      "Click it, then log in.")
                return redirect(url_for("login"))
            except auth.LoginError as e:
                error = str(e)

    return render_template("login.html", mode="signup", email=email, error=error, next_page="")


@app.route("/logout", methods=["POST"])
def logout():
    """Log out. (POST, not GET, so a link on another site can't log you out.)"""
    auth.forget_user()
    flash("You've been logged out.")
    return redirect(url_for("login"))


# ---------- Pages ----------

@app.route("/")
@auth.login_required
def home():
    """Home page: a grid of month cards."""
    return render_template("home.html")


@app.route("/month/<month>")
@auth.login_required
def month_dashboard(month):
    """Dashboard for one month, e.g. /month/2026-11."""
    if not is_valid_month(month):
        abort(404)
    # The template reads the month from here to know which data to load
    return render_template("index.html", month=month)


def month_label_for(month):
    """Turn "2026-12" into "December 2026"."""
    return datetime.strptime(month, "%Y-%m").strftime("%B %Y")


# ---------- Reading budgets from the database ----------

def data_owner_id():
    """Whose budgets the pages show.

    For now that's DEV_USER_ID, who owns the sample data that seed.py
    copied into the database. Changing this one line to
    auth.current_user_id() will make each person see their own budgets.
    """
    return db.DEV_USER_ID


def to_float(value):
    """Postgres returns money columns (numeric) as Decimal. JSON needs a plain number."""
    return float(value)


def no_budget():
    """The reply when a month has no budget."""
    return jsonify({"error": "No budget for this month"}), 404


def find_budget(month):
    """This user's budget row for one month, or None if there isn't one."""
    # The budgets table allows only one row per (user_id, month), so this
    # finds at most one row.
    return db.query(
        "select id, month, spending_limit from budgets "
        "where user_id = %s and month = %s",
        (data_owner_id(), month), one=True)


def find_previous_budget(month):
    """The latest budget before this month (usually last month), or None."""
    # "YYYY-MM" text sorts in date order, so month < '2026-12' means "earlier".
    # Newest first, keep only the first row: the closest earlier month.
    # If a month was skipped, this goes back further.
    return db.query(
        "select id, month, spending_limit from budgets "
        "where user_id = %s and month < %s "
        "order by month desc limit 1",
        (data_owner_id(), month), one=True)


def planned_categories(budget_id):
    """A budget's categories and planned amounts, in their saved order."""
    # position is the order they were entered in, which decides each
    # category's chart color.
    return db.query(
        "select category, amount from planned_expenses "
        "where budget_id = %s order by position",
        (budget_id,))


def form_data(budget):
    """A budget row in the shape the setup form uses (limit plus a list of rows)."""
    return {
        "spending_limit": to_float(budget["spending_limit"]),
        "categories": [{"name": row["category"], "amount": to_float(row["amount"])}
                       for row in planned_categories(budget["id"])],
    }


def current_and_next_month():
    """Today's month and next month as "YYYY-MM", e.g. ("2026-12", "2027-01")."""
    today = date.today()
    if today.month == 12:
        following = date(today.year + 1, 1, 1)
    else:
        following = date(today.year, today.month + 1, 1)
    return today.strftime("%Y-%m"), following.strftime("%Y-%m")


@app.route("/setup/<month>")
@auth.login_required
def setup(month):
    """Set up a new budget, or edit an existing one, e.g. /setup/2026-12."""
    if not is_valid_month(month):
        abort(404)

    # If this month already has a budget, send it to the page to fill in the form
    budget = find_budget(month)
    existing = form_data(budget) if budget else None

    # For a new budget, also send last month's budget so it can be copied
    previous = None
    if existing is None:
        previous_budget = find_previous_budget(month)
        if previous_budget:
            previous = form_data(previous_budget)
            previous["month_label"] = month_label_for(previous_budget["month"])

    if existing:
        heading = f"Edit your {month_label_for(month)} budget"
    else:
        heading = f"Set up your {month_label_for(month)} budget"

    return render_template("setup.html", month=month, heading=heading,
                           existing=existing, previous=previous)


# ---------- Data (JSON) ----------

@app.route("/budgets")
@auth.login_required
def list_budgets():
    """Every month with a budget, plus this month and next month, oldest first.

    The home page picks out the months in the year it's showing.
    """
    # Each budget with the total of all its expenses.
    # LEFT JOIN keeps budgets that have no expenses yet: their sum is NULL,
    # and coalesce() turns that into 0.
    rows = db.query(
        "select b.month, b.spending_limit, coalesce(sum(e.amount), 0) as spent "
        "from budgets b "
        "left join expenses e on e.budget_id = b.id "
        "where b.user_id = %s "
        "group by b.id, b.month, b.spending_limit "
        "order by b.month",
        (data_owner_id(),))

    months = {row["month"]: {"month": row["month"], "set_up": True,
                             "spending_limit": to_float(row["spending_limit"]),
                             "spent": to_float(row["spent"])}
              for row in rows}

    # Always include this month and next month, so there's somewhere to start
    # a new budget. Without a budget they show as "Not set up".
    for month in current_and_next_month():
        if month not in months:
            months[month] = {"month": month, "set_up": False,
                             "spending_limit": None, "spent": 0}

    return jsonify([months[m] for m in sorted(months)])


@app.route("/budgets", methods=["POST"])
@auth.login_required
def save_budget():
    """Save a budget from the setup page, then tell the page where to go next.

    Creates the month's budget, or updates it if one already exists:
    the limit is changed and the categories are replaced.
    """
    data = request.get_json(silent=True) or {}

    month = text_of(data.get("month"))
    if not is_valid_month(month):
        return jsonify({"errors": {"form": "That month isn't valid."}}), 400

    # Check everything again here: never trust the browser's checks alone
    errors, limit, planned = validate_budget(data)
    if errors:
        return jsonify({"errors": errors}), 400

    conn = db.get_db()
    # Everything inside this block is one transaction: when it ends, it's all
    # saved together. If any step fails, psycopg undoes all of it, so a
    # budget is never left half-saved.
    with conn.transaction():
        existing = find_budget(month)

        if existing:
            # Categories that already have expenses can't be removed or renamed,
            # or those expenses would no longer match any category.
            # DISTINCT lists each category once, however many expenses it has.
            rows = db.query(
                "select distinct category from expenses "
                "where budget_id = %s order by category",
                (existing["id"],))
            missing = [row["category"] for row in rows if row["category"] not in planned]
            if missing:
                return jsonify({"errors": {"form": in_use_message(missing)}}), 400

        # Create the budget, or update its limit if this user already has one
        # for this month. (user_id, month) is unique in the table, so
        # "on conflict" catches an existing budget and updates it instead.
        # "returning id" gives back the budget's id either way.
        budget_id = db.query(
            "insert into budgets (user_id, month, spending_limit) values (%s, %s, %s) "
            "on conflict (user_id, month) do update set spending_limit = excluded.spending_limit "
            "returning id",
            (data_owner_id(), month, round(limit, 2)), one=True)["id"]

        # Replace the categories: remove the old list...
        db.query("delete from planned_expenses where budget_id = %s", (budget_id,))
        # ...then insert the new one, numbering them 0, 1, 2... in form order
        for position, (category, amount) in enumerate(planned.items()):
            db.query(
                "insert into planned_expenses (budget_id, category, amount, position) "
                "values (%s, %s, %s, %s)",
                (budget_id, category, amount, position))

    conn.commit()  # make sure it's saved before telling the browser it worked

    # The setup page sends the browser here after saving
    return jsonify({"redirect": f"/month/{month}"})


def in_use_message(categories):
    """The error for trying to remove or rename categories that have expenses."""
    names = ", ".join(f'"{c}"' for c in categories)
    if len(categories) == 1:
        return (f"{names} already has expenses logged this month, so it can't be "
                f"removed or renamed. Add it back to save your changes.")
    return (f"{names} already have expenses logged this month, so they can't be "
            f"removed or renamed. Add them back to save your changes.")


@app.route("/budgets/<month>/summary")
@auth.login_required
def summary(month):
    """Planned vs. actual for each category in one month (used by the dashboard)."""
    budget = find_budget(month) if is_valid_month(month) else None
    if budget is None:
        return no_budget()

    # One row per planned category, with the total spent in it.
    # LEFT JOIN keeps categories with no expenses yet (total 0).
    # GROUP BY adds up each category's expenses; ORDER BY position keeps
    # the categories in their saved order, so their colors stay the same.
    rows = db.query(
        "select p.category, p.amount as planned, coalesce(sum(e.amount), 0) as actual "
        "from planned_expenses p "
        "left join expenses e on e.budget_id = p.budget_id and e.category = p.category "
        "where p.budget_id = %s "
        "group by p.id, p.category, p.amount, p.position "
        "order by p.position",
        (budget["id"],))

    limit = to_float(budget["spending_limit"])
    actual = [to_float(row["actual"]) for row in rows]
    return jsonify({
        "month": month,
        "spending_limit": limit,
        "categories": [row["category"] for row in rows],
        "planned": [to_float(row["planned"]) for row in rows],
        "actual": actual,
        "remaining": limit - sum(actual),
    })


@app.route("/budgets/<month>/expenses", methods=["POST"])
@auth.login_required
def add_expense(month):
    """Record an expense in one of this month's categories."""
    # find_budget() only looks at this user's budgets, so you can't add
    # expenses to someone else's month
    budget = find_budget(month) if is_valid_month(month) else None
    if budget is None:
        return no_budget()

    body = request.get_json(silent=True) or {}
    category = body.get("category")
    note = text_of(body.get("note"))

    try:
        amount = round(float(body.get("amount")), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number."}), 400
    if not math.isfinite(amount):  # float() also accepts "inf" and "nan"
        return jsonify({"error": "Amount must be a number."}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero."}), 400

    # The category has to be one of this month's planned categories
    categories = [row["category"] for row in planned_categories(budget["id"])]
    if category not in categories:
        return jsonify({"error": "Pick a valid category."}), 400

    # Date it today if this is the current month. For another month, use its
    # 1st, so the expense still falls inside that month.
    this_month, _ = current_and_next_month()
    spent_on = date.today() if month == this_month else date(*map(int, month.split("-")), 1)

    # Save it. An empty note is stored as NULL (no note).
    row = db.query(
        "insert into expenses (budget_id, category, amount, spent_on, note) "
        "values (%s, %s, %s, %s, %s) returning id",
        (budget["id"], category, amount, spent_on, note or None), one=True)
    db.get_db().commit()  # make sure it's saved before telling the browser it worked

    return jsonify({"id": row["id"], "category": category, "amount": amount, "note": note}), 201


if __name__ == "__main__":
    app.run(debug=True, port=5001)
