from datetime import date, datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

MAX_GAMES_PER_DAY = 3
MAX_GUESSES_PER_GAME = 5
WORD_LENGTH = 5


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default="player")  # 'admin' or 'player'

    sessions = db.relationship("GameSession", backref="user", lazy=True)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def is_admin(self):
        return self.role == "admin"


class Word(db.Model):
    __tablename__ = "words"

    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(5), unique=True, nullable=False)


class GameSession(db.Model):
    __tablename__ = "game_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey("words.id"), nullable=False)
    play_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(15), nullable=False, default="in_progress")
    # 'in_progress', 'won', 'lost'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    word = db.relationship("Word")
    guesses = db.relationship(
        "Guess", backref="session", lazy=True, order_by="Guess.guess_number"
    )

    def attempts_used(self):
        return len(self.guesses)

    def attempts_remaining(self):
        return MAX_GUESSES_PER_GAME - self.attempts_used()


class Guess(db.Model):
    __tablename__ = "guesses"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("game_sessions.id"), nullable=False)
    guess_word = db.Column(db.String(5), nullable=False)
    feedback = db.Column(db.String(20), nullable=False)  # comma separated: green,orange,grey,...
    guess_number = db.Column(db.Integer, nullable=False)
    guessed_at = db.Column(db.DateTime, default=datetime.utcnow)


def score_guess(guess_word: str, target_word: str):
    """
    Wordle-style scoring.
    Returns a list of 5 labels: 'green' | 'orange' | 'grey'
    Handles duplicate letters correctly (two-pass algorithm).
    """
    guess_word = guess_word.upper()
    target_word = target_word.upper()
    result = ["grey"] * WORD_LENGTH
    target_letters = list(target_word)

    # Pass 1: exact matches (green) - consume from target_letters
    for i in range(WORD_LENGTH):
        if guess_word[i] == target_word[i]:
            result[i] = "green"
            target_letters[i] = None

    # Pass 2: right letter, wrong position (orange)
    for i in range(WORD_LENGTH):
        if result[i] == "green":
            continue
        letter = guess_word[i]
        if letter in target_letters:
            result[i] = "orange"
            target_letters[target_letters.index(letter)] = None

    return result


SEED_WORDS = [
    "APPLE", "BRAVE", "CRANE", "DELTA", "EAGLE",
    "FLAME", "GHOST", "HOUSE", "IVORY", "JOKER",
    "KNIFE", "LEMON", "MANGO", "NORTH", "OCEAN",
    "PIANO", "QUEEN", "RIVER", "STONE", "TIGER",
]
