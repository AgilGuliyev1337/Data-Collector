"""Postgres bağlantı qatı. Bütün credential-lar .env-dən gəlir."""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_dsn(test: bool = False) -> str:
    key = "TEST_DATABASE_URL" if test else "DATABASE_URL"
    dsn = os.environ.get(key)
    if not dsn:
        raise RuntimeError(f"{key} .env faylında təyin olunmayıb")
    return dsn


def get_connection(test: bool = False):
    return psycopg2.connect(get_dsn(test=test))
