from flask import Flask, jsonify, render_template

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


if __name__ == "__main__":
    app.run(debug=True)
