import os
import sys
from pathlib import Path

# Must be set before the app is imported: tests use an in-memory database and never call the AI.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import app as flask_app  # noqa: E402
from extensions import db  # noqa: E402


@pytest.fixture
def client():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app.test_client()


def page(client, url="/troubleshoot/interview"):
    return client.get(url).get_data(as_text=True)


def start(client, problem):
    return client.post("/troubleshoot", data={"problem": problem}, follow_redirects=True).get_data(as_text=True)