import os
import re
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from sqlalchemy import func

from models import (
    db, User, Word, GameSession, Guess, score_guess,
    SEED_WORDS, MAX_GAMES_PER_DAY, MAX_GUESSES_PER_GAME, WORD_LENGTH
)
import random

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "guess_word.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
USERNAME_RE_LOWER = re.compile(r"[a-z]")
USERNAME_RE_UPPER = re.compile(r"[A-Z]")
PASSWORD_SPECIAL_CHARS = set("$%*&")


def validate_username(username):
    if not username or len(username) < 5:
        return "Username must have at least 5 letters."
    letters = [c for c in username if c.isalpha()]
    if len(letters) < 5:
        return "Username must have at least 5 letters."
    if not USERNAME_RE_LOWER.search(username):
        return "Username must contain at least one lowercase letter."
    if not USERNAME_RE_UPPER.search(username):
        return "Username must contain at least one uppercase letter."
    return None


def validate_password(password):
    if not password or len(password) < 5:
        return "Password must be at least 5 characters long."
    has_alpha = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in PASSWORD_SPECIAL_CHARS for c in password)
    if not has_alpha:
        return "Password must contain at least one letter."
    if not has_digit:
        return "Password must contain at least one number."
    if not has_special:
        return "Password must contain at least one special character ($, %, *, &)."
    return None


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not current_user.is_admin():
            flash("Admin access required.", "error")
            return redirect(url_for("game_home"))
        return view_func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("game_home"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "player")
        if role not in ("player", "admin"):
            role = "player"

        username_error = validate_username(username)
        password_error = validate_password(password)

        if username_error:
            flash(username_error, "error")
            return render_template("register.html")
        if password_error:
            flash(password_error, "error")
            return render_template("register.html")
        if User.query.filter_by(username=username).first():
            flash("Username already taken.", "error")
            return render_template("register.html")

        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            if user.is_admin():
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("game_home"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Player game routes
# ---------------------------------------------------------------------------
def games_played_today(user_id):
    today = date.today()
    return GameSession.query.filter_by(user_id=user_id, play_date=today).count()


def get_active_session(user_id):
    return GameSession.query.filter_by(
        user_id=user_id, play_date=date.today(), status="in_progress"
    ).first()


@app.route("/game")
@login_required
def game_home():
    if current_user.is_admin():
        return redirect(url_for("admin_dashboard"))

    active_session = get_active_session(current_user.id)
    played_today = games_played_today(current_user.id)
    games_left = max(0, MAX_GAMES_PER_DAY - played_today)

    return render_template(
        "game.html",
        active_session=active_session,
        games_left=games_left,
        max_games=MAX_GAMES_PER_DAY,
        max_guesses=MAX_GUESSES_PER_GAME,
        word_length=WORD_LENGTH,
    )


@app.route("/game/start", methods=["POST"])
@login_required
def game_start():
    if current_user.is_admin():
        return jsonify({"error": "Admins cannot play."}), 403

    if get_active_session(current_user.id):
        return jsonify({"error": "You already have a game in progress."}), 400

    if games_played_today(current_user.id) >= MAX_GAMES_PER_DAY:
        return jsonify({"error": "You have reached the daily limit of 3 words."}), 400

    words = Word.query.all()
    if not words:
        return jsonify({"error": "No words configured. Contact admin."}), 500

    chosen = random.choice(words)
    session_row = GameSession(user_id=current_user.id, word_id=chosen.id, play_date=date.today())
    db.session.add(session_row)
    db.session.commit()

    return jsonify({
        "session_id": session_row.id,
        "guesses": [],
        "attempts_remaining": MAX_GUESSES_PER_GAME,
        "status": "in_progress",
    })


@app.route("/game/guess", methods=["POST"])
@login_required
def game_guess():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    guess_word = (data.get("guess") or "").strip().upper()

    session_row = GameSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session_row:
        return jsonify({"error": "Game session not found."}), 404
    if session_row.status != "in_progress":
        return jsonify({"error": "This game has already ended."}), 400

    if len(guess_word) != WORD_LENGTH or not guess_word.isalpha():
        return jsonify({"error": "Guess must be a 5-letter word (letters only)."}), 400

    if session_row.attempts_used() >= MAX_GUESSES_PER_GAME:
        return jsonify({"error": "No attempts remaining."}), 400

    target_word = session_row.word.word
    feedback = score_guess(guess_word, target_word)

    guess_row = Guess(
        session_id=session_row.id,
        guess_word=guess_word,
        feedback=",".join(feedback),
        guess_number=session_row.attempts_used() + 1,
    )
    db.session.add(guess_row)

    won = guess_word == target_word
    attempts_used = session_row.attempts_used() + 1  # including this guess

    if won:
        session_row.status = "won"
    elif attempts_used >= MAX_GUESSES_PER_GAME:
        session_row.status = "lost"

    db.session.commit()

    response = {
        "guess": guess_word,
        "feedback": feedback,
        "attempts_remaining": MAX_GUESSES_PER_GAME - attempts_used,
        "status": session_row.status,
    }
    if session_row.status == "lost":
        response["target_word"] = target_word

    return jsonify(response)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin_dashboard.html")


@app.route("/admin/report/daily", methods=["GET"])
@admin_required
def report_daily():
    selected_date_str = request.args.get("date", date.today().isoformat())
    try:
        selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    except ValueError:
        selected_date = date.today()
        selected_date_str = selected_date.isoformat()

    sessions = GameSession.query.filter_by(play_date=selected_date).all()
    num_users = len({s.user_id for s in sessions})
    num_correct = sum(1 for s in sessions if s.status == "won")
    num_words_tried = len(sessions)

    return render_template(
        "report_daily.html",
        selected_date=selected_date_str,
        num_users=num_users,
        num_correct=num_correct,
        num_words_tried=num_words_tried,
        sessions=sessions,
    )


@app.route("/admin/report/user", methods=["GET"])
@admin_required
def report_user():
    username = request.args.get("username", "").strip()
    rows = []
    target_user = None
    if username:
        target_user = User.query.filter_by(username=username).first()
        if target_user:
            sessions = GameSession.query.filter_by(user_id=target_user.id).all()
            by_date = {}
            for s in sessions:
                d = s.play_date.isoformat()
                by_date.setdefault(d, {"tried": 0, "correct": 0})
                by_date[d]["tried"] += 1
                if s.status == "won":
                    by_date[d]["correct"] += 1
            rows = sorted(
                [{"date": d, **v} for d, v in by_date.items()],
                key=lambda r: r["date"],
                reverse=True,
            )
        else:
            flash("No such user.", "error")

    players = User.query.filter_by(role="player").order_by(User.username).all()
    return render_template(
        "report_user.html", username=username, rows=rows, players=players, found=bool(target_user)
    )


# ---------------------------------------------------------------------------
# DB init / seeding
# ---------------------------------------------------------------------------
def init_db():
    db.create_all()
    if Word.query.count() == 0:
        for w in SEED_WORDS:
            db.session.add(Word(word=w))
        db.session.commit()

    if not User.query.filter_by(username="AdminUser").first():
        admin = User(username="AdminUser", role="admin")
        admin.set_password("Admin1$")
        db.session.add(admin)
        db.session.commit()


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True, host="0.0.0.0", port=3000)
