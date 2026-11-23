import math
from datetime import datetime

import psycopg
from flask import Flask, abort, jsonify, render_template, request

import db

app = Flask(__name__)
db.init_app(app)  # closes each request's database connection when the request ends

# The same planned amounts are used for every sample month
SAMPLE_PLAN = {"Rent": 900, "Groceries": 300, "Insurance": 150, "Phone": 60, "Fun": 200}

# Hardcoded sample budgets until the database is set up.
# Each key is a month written as "YYYY-MM".
# A value of None means the month exists but has no budget yet ("Not set up").
SAMPLE_BUDGETS = {
    # August is well over budget, for testing the over-budget chart:
    # $2,350 spent against a $2,000 limit (Fun is $700 over its $200 plan)
    "2026-08": {
        "spending_limit": 2000,
        "planned": dict(SAMPLE_PLAN),
        "actual": {"Rent": 900, "Groceries": 340, "Insurance": 150, "Phone": 60, "Fun": 900},
    },
    "2026-09": {
        "spending_limit": 2000,
        "planned": dict(SAMPLE_PLAN),
        "actual": {"Rent": 900, "Groceries": 260, "Insurance": 150, "Phone": 60, "Fun": 180},
    },
    # October is over budget: $2,080 spent against a $2,000 limit
    "2026-10": {
        "spending_limit": 2000,
        "planned": dict(SAMPLE_PLAN),
        "actual": {"Rent": 900, "Groceries": 360, "Insurance": 150, "Phone": 60, "Fun": 610},
    },
    # November is the current month, so it's only partly spent
    "2026-11": {
        "spending_limit": 2000,
        "planned": dict(SAMPLE_PLAN),
        "actual": {"Rent": 900, "Groceries": 140, "Insurance": 150, "Phone": 60, "Fun": 85},
    },
    # December hasn't been set up yet
    "2026-12": None,
}


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


def get_budget_or_404(month):
    """Return the budget for a month, or stop with a 404 error if there isn't one."""
    budget = SAMPLE_BUDGETS.get(month)
    if budget is None:
        abort(404)
    return budget


# ---------- Pages ----------

@app.route("/")
def home():
    """Home page: a grid of month cards."""
    return render_template("home.html")


@app.route("/month/<month>")
def month_dashboard(month):
    """Dashboard for one month, e.g. /month/2026-11."""
    if not is_valid_month(month):
        abort(404)
    # The template reads the month from here to know which data to load
    return render_template("index.html", month=month)


def month_label_for(month):
    """Turn "2026-12" into "December 2026"."""
    return datetime.strptime(month, "%Y-%m").strftime("%B %Y")


def form_data(budget):
    """A budget in the shape the setup form uses (limit plus a list of rows)."""
    return {
        "spending_limit": budget["spending_limit"],
        "categories": [{"name": name, "amount": amount}
                       for name, amount in budget["planned"].items()],
    }


def previous_budget_month(month):
    """The latest month before this one that has a budget, or None.

    Usually that's the month right before, but if a month was skipped
    it goes back further. "YYYY-MM" strings sort in date order, so
    comparing them with < works.
    """
    earlier = [m for m, b in SAMPLE_BUDGETS.items() if m < month and b is not None]
    return max(earlier) if earlier else None


@app.route("/setup/<month>")
def setup(month):
    """Set up a new budget, or edit an existing one, e.g. /setup/2026-12."""
    if not is_valid_month(month):
        abort(404)

    # If this month already has a budget, send it to the page to fill in the form
    budget = SAMPLE_BUDGETS.get(month)
    existing = form_data(budget) if budget is not None else None

    # For a new budget, also send last month's budget so it can be copied
    previous = None
    if existing is None:
        previous_month = previous_budget_month(month)
        if previous_month:
            previous = form_data(SAMPLE_BUDGETS[previous_month])
            previous["month_label"] = month_label_for(previous_month)

    if existing:
        heading = f"Edit your {month_label_for(month)} budget"
    else:
        heading = f"Set up your {month_label_for(month)} budget"

    return render_template("setup.html", month=month, heading=heading,
                           existing=existing, previous=previous)


# ---------- Data (JSON) ----------

@app.route("/budgets")
def list_budgets():
    """Every month with its spending limit and total spent, oldest first."""
    months = []
    for month in sorted(SAMPLE_BUDGETS):
        budget = SAMPLE_BUDGETS[month]
        if budget is None:
            months.append({"month": month, "set_up": False,
                           "spending_limit": None, "spent": 0})
        else:
            months.append({"month": month, "set_up": True,
                           "spending_limit": budget["spending_limit"],
                           "spent": sum(budget["actual"].values())})
    return jsonify(months)


@app.route("/budgets", methods=["POST"])
def save_budget():
    """Save a budget from the setup page, then tell the page where to go next.

    Stored in memory for now, so it resets when the server restarts.
    """
    data = request.get_json(silent=True) or {}

    month = text_of(data.get("month"))
    if not is_valid_month(month):
        return jsonify({"errors": {"form": "That month isn't valid."}}), 400

    # Check everything again here: never trust the browser's checks alone
    errors, limit, planned = validate_budget(data)
    if errors:
        return jsonify({"errors": errors}), 400

    old = SAMPLE_BUDGETS.get(month) or {}
    old_actual = old.get("actual", {})

    SAMPLE_BUDGETS[month] = {
        "spending_limit": round(limit, 2),
        "planned": planned,
        # When editing, keep what's already been spent in categories that
        # still exist. New categories start at $0 spent.
        "actual": {name: old_actual.get(name, 0) for name in planned},
        "expenses": old.get("expenses", []),
    }

    # The setup page sends the browser here after saving
    return jsonify({"redirect": f"/month/{month}"})


@app.route("/budgets/<month>/summary")
def summary(month):
    """Planned vs. actual for each category in one month (used by the dashboard)."""
    b = get_budget_or_404(month)
    categories = list(b["planned"].keys())
    planned = [b["planned"][c] for c in categories]
    actual = [b["actual"].get(c, 0) for c in categories]
    return jsonify({
        "month": month,
        "spending_limit": b["spending_limit"],
        "categories": categories,
        "planned": planned,
        "actual": actual,
        "remaining": b["spending_limit"] - sum(actual),
    })


@app.route("/budgets/<month>/expenses", methods=["POST"])
def add_expense(month):
    """Record an expense/payment and add it to that category's actual total.

    Stored in memory for now, so it resets when the server restarts.
    """
    budget = get_budget_or_404(month)
    body = request.get_json(silent=True) or {}
    category = body.get("category")
    note = (body.get("note") or "").strip()

    try:
        amount = round(float(body.get("amount")), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number."}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero."}), 400
    if category not in budget["planned"]:
        return jsonify({"error": "Pick a valid category."}), 400

    actual = budget["actual"]
    actual[category] = round(actual.get(category, 0) + amount, 2)
    expense = {"category": category, "amount": amount, "note": note}
    budget.setdefault("expenses", []).append(expense)
    return jsonify(expense), 201


# ---------- Database check (temporary, Phase 1) ----------

@app.route("/health/db")
def health_db():
    """Check that the app can reach Supabase: counts the rows in budgets."""
    try:
        row = db.query("select count(*) as n from budgets", one=True)
        return jsonify({"ok": True, "budgets": row["n"]})
    except db.DatabaseConfigError as e:
        # .env problem (missing or wrong kind of URL). The message never includes the URL.
        return jsonify({"ok": False, "error": str(e)}), 500
    except psycopg.OperationalError:
        # Couldn't connect. psycopg's own message can include parts of the
        # connection string, so it's replaced with a safe one.
        return jsonify({"ok": False, "error": "Could not connect to the database. "
                        "Check SUPABASE_URL in .env and your internet connection."}), 500
    except psycopg.Error as e:
        # Connected, but the query failed (for example, no budgets table yet).
        # These messages come from the database and don't contain the URL.
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
