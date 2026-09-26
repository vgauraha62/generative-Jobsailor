import pytest

from tests.conftest import make_client, reset_user, drop_user

UID = 202


@pytest.fixture()
def authed():
    reset_user(UID, "dash@run.com", "Dash")
    yield make_client(UID)
    drop_user(UID)


def test_generate_ships_submittable(authed):
    html = authed.get("/dashboard").text
    assert 'id="free-types"' in html
    assert 'value="backend, golang"' not in html  # defaults alone must not exceed max types
    assert "new Set(" in html  # chip + free-typed dupes collapsed


def test_theme_toggle_wired(authed):
    html = authed.get("/dashboard").text
    assert "/static/assets/theme.js" in html  # toggle script present
    assert "js_theme" in html  # pre-paint default (light) present
    css = authed.get("/static/assets/app.css").text
    assert 'html[data-theme="light"]' in css  # light override block
    assert ".royal-chat-drawer" in css  # drawer themed too
