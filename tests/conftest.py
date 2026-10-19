import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.seeds.seed_data import SEED_PASSWORD, run_seed


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        run_seed()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def login(client):
    def _login(login_id, password=SEED_PASSWORD):
        return client.post("/login", data={"login_id": login_id, "password": password}, follow_redirects=True)
    return _login
