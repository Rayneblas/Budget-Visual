from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Hardcoded sample budget until the database is set up
SAMPLE_BUDGET = {
    "month": "2026-10",
    "spending_limit": 2000,
    "planned": {"Rent": 900, "Groceries": 300, "Insurance": 150, "Phone": 60, "Fun": 200},
    "actual": {"Rent": 900, "Groceries": 180, "Insurance": 150, "Phone": 60, "Fun": 260},
}


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/budgets/<budget_id>/summary")
def summary(budget_id):
    b = SAMPLE_BUDGET
    categories = list(b["planned"].keys())
    planned = [b["planned"][c] for c in categories]
    actual = [b["actual"].get(c, 0) for c in categories]
    return jsonify({
        "budget_id": budget_id,
        "month": b["month"],
        "spending_limit": b["spending_limit"],
        "categories": categories,
        "planned": planned,
        "actual": actual,
        "remaining": b["spending_limit"] - sum(actual),
    })


@app.route("/budgets/<budget_id>/expenses", methods=["POST"])
def add_expense(budget_id):
    """Record an expense/payment and add it to that category's actual total.

    Stored in memory for now, so it resets when the server restarts.
    """
    body = request.get_json(silent=True) or {}
    category = body.get("category")
    note = (body.get("note") or "").strip()

    try:
        amount = round(float(body.get("amount")), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number."}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero."}), 400
    if category not in SAMPLE_BUDGET["planned"]:
        return jsonify({"error": "Pick a valid category."}), 400

    actual = SAMPLE_BUDGET["actual"]
    actual[category] = round(actual.get(category, 0) + amount, 2)
    expense = {"category": category, "amount": amount, "note": note}
    SAMPLE_BUDGET.setdefault("expenses", []).append(expense)
    return jsonify(expense), 201


if __name__ == "__main__":
    app.run(debug=True, port=5001)
