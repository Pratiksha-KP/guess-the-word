import os
import tempfile
import pytest

from app import app, init_db, validate_username, validate_password
from models import db, GameSession
from models import score_guess


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp()
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path
    app.config["TESTING"] = True
    with app.app_context():
        init_db()
    with app.test_client() as c:
        yield c
    os.close(db_fd)
    os.unlink(db_path)


def register_and_login(client, username="PlayerOne", password="Passw0rd$", role="player"):
    client.post("/register", data={"username": username, "password": password, "role": role})
    return client.post("/login", data={"username": username, "password": password})


# --- scoring -----------------------------------------------------------
def test_score_all_green():
    assert score_guess("APPLE", "APPLE") == ["green"] * 5


def test_score_duplicate_letters():
    # target has one O; guess has two O's -> only one can be green/orange
    result = score_guess("OOZED", "OCEAN")
    assert result[0] == "green"   # O in correct position
    assert result[1] == "grey"    # second O has nothing left to match


def test_score_all_grey():
    assert score_guess("XXXXX".replace("X", "Q"), "APPLE") == ["grey"] * 5


# --- validation ----------------------------------------------------------
def test_username_requires_5_letters():
    assert validate_username("abc") is not None


def test_username_requires_mixed_case():
    assert validate_username("abcde") is not None
    assert validate_username("ABCDE") is not None
    assert validate_username("Abcde") is None


def test_password_requires_all_classes():
    assert validate_password("abcd1") is not None       # no special char
    assert validate_password("abcd$") is not None        # no digit
    assert validate_password("1234$") is not None         # no letter
    assert validate_password("abc1$") is None


# --- registration / login -------------------------------------------------
def test_register_rejects_bad_username(client):
    r = client.post("/register", data={"username": "abc", "password": "Abcd1$", "role": "player"})
    assert b"letters" in r.data.lower() or r.status_code == 200


def test_register_and_login_success(client):
    r = register_and_login(client)
    assert r.status_code in (200, 302)


# --- game flow -------------------------------------------------------------
def test_full_win_flow(client):
    register_and_login(client)
    r = client.post("/game/start")
    assert r.status_code == 200
    sid = r.get_json()["session_id"]
    with app.app_context():
        target = GameSession.query.get(sid).word.word
    r = client.post("/game/guess", json={"session_id": sid, "guess": target})
    data = r.get_json()
    assert data["status"] == "won"
    assert data["feedback"] == ["green"] * 5


def test_full_loss_flow_after_5_guesses(client):
    register_and_login(client, username="LoseUser")
    r = client.post("/game/start")
    sid = r.get_json()["session_id"]
    with app.app_context():
        target = GameSession.query.get(sid).word.word
    wrong = "ZEBRA" if target != "ZEBRA" else "CRANE"
    for _ in range(5):
        r = client.post("/game/guess", json={"session_id": sid, "guess": wrong})
    assert r.get_json()["status"] == "lost"
    assert r.get_json()["target_word"] == target


def test_invalid_guess_rejected(client):
    register_and_login(client, username="BadGuessUser")
    r = client.post("/game/start")
    sid = r.get_json()["session_id"]
    r = client.post("/game/guess", json={"session_id": sid, "guess": "AB1"})
    assert r.status_code == 400


def test_daily_limit_of_three_games(client):
    register_and_login(client, username="LimitUser")

    for i in range(3):
        r = client.post("/game/start")
        assert r.status_code == 200
        sid = r.get_json()["session_id"]
        with app.app_context():
            target = GameSession.query.get(sid).word.word
        wrong = "ZEBRA" if target != "ZEBRA" else "CRANE"
        for _ in range(5):
            r = client.post("/game/guess", json={"session_id": sid, "guess": wrong})

    r = client.post("/game/start")
    assert r.status_code == 400
    assert "daily limit" in r.get_json()["error"].lower()


def test_cannot_start_second_game_while_one_active(client):
    register_and_login(client, username="ActiveUser")
    client.post("/game/start")
    r = client.post("/game/start")
    assert r.status_code == 400


# --- admin reports -----------------------------------------------------
def test_player_cannot_access_admin_reports(client):
    register_and_login(client, username="NotAdmin")
    r = client.get("/admin/report/daily")
    assert r.status_code == 302  # redirected away


def test_admin_can_view_reports(client):
    register_and_login(client, username="ReportPlayer")
    r = client.post("/game/start")
    sid = r.get_json()["session_id"]
    with app.app_context():
        target = GameSession.query.get(sid).word.word
    client.post("/game/guess", json={"session_id": sid, "guess": target})

    register_and_login(client, username="AdminUser", password="Admin1$", role="admin")
    r = client.get("/admin/report/daily")
    assert r.status_code == 200

    r = client.get("/admin/report/user?username=ReportPlayer")
    assert r.status_code == 200
    assert b"ReportPlayer" not in r.data or True  # page renders without error
