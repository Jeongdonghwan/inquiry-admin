import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    ENV = os.getenv("FLASK_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or "sqlite:///dev.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = ENV == "production"
    WTF_CSRF_TIME_LIMIT = None

    RATELIMIT_STORAGE_URI = "memory://"

    SMS_PROVIDER = os.getenv("SMS_PROVIDER", "dummy")
    SMS_DEFAULT_SENDER = os.getenv("SMS_DEFAULT_SENDER", "0200000000")
    ALIGO_API_KEY = os.getenv("ALIGO_API_KEY", "")
    ALIGO_USER_ID = os.getenv("ALIGO_USER_ID", "")
    ALIGO_TESTMODE = os.getenv("ALIGO_TESTMODE", "Y")

    ADMIN_BASE_URL = os.getenv("ADMIN_BASE_URL", "http://localhost:5100")
    COMPANY_NAME = os.getenv("COMPANY_NAME", "[회사명]")
    REPRESENTATIVE_PHONE = os.getenv("REPRESENTATIVE_PHONE", "[대표번호]")


class TestConfig(Config):
    ENV = "testing"
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    RATELIMIT_ENABLED = False
