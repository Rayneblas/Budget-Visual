# Budget-Visual

## How to run

1. Install the packages:
   ```
   pip3 install -r requirements.txt
   ```
2. Create a `.env` file in the project folder with these variables
   (ask the project owner for the values; never commit this file):
   - `DATABASE_URL`: the Supabase Postgres connection string (starts with `postgresql://`)
   - `SUPABASE_URL`: the Supabase project address (`https://<project>.supabase.co`)
   - `SUPABASE_KEY`: the Supabase publishable key (starts with `sb_publishable_`)
   - `SECRET_KEY`: any long random text, used to sign login cookies
3. Start the app:
   ```
   python3 app.py
   ```
4. Open http://127.0.0.1:5001 (the app runs on port 5001) and sign up.

## Loading sample data

`seed.py` fills an account with sample budgets for August to November 2026,
including over-budget months, so the charts have something to show.

1. Sign up in the app first.
2. Run it with that account's email:
   ```
   python3 seed.py you@example.com
   ```

Warning: this deletes **all** of that account's existing budgets before
adding the sample data.
