from backend.app.main import app


def test_api_uses_dubloom_public_title():
    assert app.title == "Dubloom API"
