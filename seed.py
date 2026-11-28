"""Copy the sample data below into the Supabase tables, for one account.

Run it with the email of an account you've signed up with in the app:
    python3 seed.py you@example.com

What it does, all in one transaction (if anything fails, nothing is saved):
1. Looks up the account's id in Supabase's auth.users table. If there's
   no account with that email, it stops without changing anything.
2. Deletes ALL of that account's existing budgets, including any you made
   in the app. The database's ON DELETE CASCADE also removes their
   planned_expenses and expenses, so running this twice doesn't create
   duplicates.
3. For each sample month that has a budget, inserts:
   - one row in budgets
   - one row in planned_expenses per category, with position 0, 1, 2...
     in the current order (the order decides each category's chart color)
   - one row in expenses per category with spending, because the sample
     data only has a total per category, not individual purchases. Each one
     is dated the 15th of its month with the note "Sample data".
Months with no budget (None in SAMPLE_BUDGETS) are skipped.
"""
import sys
from datetime import date

import db

# The same planned amounts are used for every sample month
SAMPLE_PLAN = {"Rent": 900, "Groceries": 300, "Insurance": 150, "Phone": 60, "Fun": 200}

# The sample budgets this script copies into the database.
# Each key is a month written as "YYYY-MM"; "actual" is the total spent per category.
# A value of None means the month has no budget yet ("Not set up").
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


def find_user_id(email):
    """The id of the account with this email, or None if there isn't one."""
    # auth.users is Supabase's own table of accounts. lower() on both sides
    # makes the match ignore capital letters ("Ray@x.com" = "ray@x.com").
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("select id from auth.users where lower(email) = lower(%s)", (email,))
        row = cur.fetchone()
    return row["id"] if row else None


def seed(user_id):
    """Replace this user's budgets with the sample data. Returns what was done."""
    counts = {"budgets": 0, "planned_expenses": 0, "expenses": 0}
    months_added = []

    # "with" commits when the block finishes, or rolls everything back on an error
    with db.connect() as conn, conn.cursor() as cur:

        # 1. Remove this user's existing budgets (and, by cascade, their categories and expenses)
        cur.execute("delete from budgets where user_id = %s", (user_id,))
        counts["deleted"] = cur.rowcount

        # 2. Insert each month, oldest first
        for month in sorted(SAMPLE_BUDGETS):
            budget = SAMPLE_BUDGETS[month]
            if budget is None:
                continue  # "Not set up" months have no row in the database

            # The budget itself. "returning id" gives back the id the database made.
            cur.execute(
                "insert into budgets (user_id, month, spending_limit) "
                "values (%s, %s, %s) returning id",
                (user_id, month, budget["spending_limit"]),
            )
            budget_id = cur.fetchone()["id"]
            counts["budgets"] += 1
            months_added.append(month)

            # Planned categories, keeping their order with a position number
            for position, (category, amount) in enumerate(budget["planned"].items()):
                cur.execute(
                    "insert into planned_expenses (budget_id, category, amount, position) "
                    "values (%s, %s, %s, %s)",
                    (budget_id, category, amount, position),
                )
                counts["planned_expenses"] += 1

            # One expense per category for its total, dated the 15th of the month
            year, month_number = map(int, month.split("-"))
            spent_on = date(year, month_number, 15)
            for category, amount in budget["actual"].items():
                if amount <= 0:
                    continue  # the expenses table only allows amounts above 0
                cur.execute(
                    "insert into expenses (budget_id, category, amount, spent_on, note) "
                    "values (%s, %s, %s, %s, %s)",
                    (budget_id, category, amount, spent_on, "Sample data"),
                )
                counts["expenses"] += 1

    # The connection has committed by this point
    counts["months"] = months_added
    return counts


def main():
    # sys.argv is the command split into words: ["seed.py", "you@example.com"]
    if len(sys.argv) != 2:
        print("Usage: python3 seed.py you@example.com")
        print("Loads the sample budgets into that account (sign up in the app first).")
        sys.exit(1)

    email = sys.argv[1].strip()
    user_id = find_user_id(email)
    if user_id is None:
        print("No account with that email. Sign up in the app first.")
        sys.exit(1)

    counts = seed(user_id)
    print(f"Removed {counts['deleted']} existing budget(s) for {email}.")
    print(f"Inserted {counts['budgets']} budgets ({', '.join(counts['months'])}),")
    print(f"  {counts['planned_expenses']} planned categories and {counts['expenses']} expenses.")


if __name__ == "__main__":
    main()
