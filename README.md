# Guess the Word

A Wordle-style word-guessing game built with Flask + SQLite, with two roles:

- **Player** — registers, logs in, and plays up to 3 words per day (5 guesses per word).
- **Admin** — views a daily report (users played / correct guesses) and a per-user report
  (date, words tried, correct guesses).

## Stack
- Python 3, Flask, Flask-SQLAlchemy, Flask-Login
- SQLite (file-based, zero setup)
- Vanilla JS + CSS for the game board (no frontend framework needed)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
python app.py
```

The app runs at `http://127.0.0.1:5000`. On first run it auto-creates the SQLite DB,
seeds 20 five-letter words, and creates a default admin account:

- **username:** `AdminUser`
- **password:** `Admin1$`

Change or remove this in `init_db()` before deploying anywhere real.

## Validation rules
- **Username:** at least 5 letters, must contain both an uppercase and a lowercase letter.
- **Password:** at least 5 characters, must contain a letter, a digit, and one of `$ % * &`.

## Game rules implemented
- One active word per player at a time; max **3 words/day** per player (enforced server-side
  by date, not just client state).
- Max **5 guesses** per word, guesses must be 5-letter alphabetic words (submitted/stored uppercase).
- Feedback per letter uses the standard Wordle two-pass algorithm (handles duplicate letters
  correctly): **green** = right letter & position, **orange** = right letter & wrong position,
  **grey** = letter not in word.
- Win → congratulatory modal; on OK, the game ends. Exhaust 5 guesses without winning →
  "better luck next time" modal revealing the word; on OK, the game ends.
- Previous guesses for the current word stay visible in the grid in the order they were made.
- Every guess is persisted (`guesses` table) with a timestamp, alongside the session's word
  and date (`game_sessions` table), so reports can be reconstructed from the DB alone.

## Admin reports
- `/admin/report/daily?date=YYYY-MM-DD` — users who played that day, words attempted, and
  correct guesses.
- `/admin/report/user?username=...` — per-date breakdown of words tried and correct guesses
  for one player.

## Data model
- `users(id, username, password_hash, role)`
- `words(id, word)` — the 20 seed words
- `game_sessions(id, user_id, word_id, play_date, status)` — one row per word attempt
- `guesses(id, session_id, guess_word, feedback, guess_number, guessed_at)` — one row per guess

## Notes / possible extensions
- Passwords are hashed with Werkzeug's `generate_password_hash` (never stored in plaintext).
- The daily-limit and guess-count checks are all enforced server-side, so they can't be
  bypassed by refreshing the page or calling the API directly.
- Not yet handled (fair game to add if time allows): password reset, admin UI for adding/
  removing words, pagination on the reports for large datasets, and unit tests (the manual
  test script used during development covered scoring, validation, win/loss, and the daily
  limit — worth turning into a `pytest` suite for the submission).
