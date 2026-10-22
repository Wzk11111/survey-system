# 测试用独立的库，跑完再清一次，避免互相污染
# -*- coding: utf-8 -*-
import os
import sys

os.environ["MONGO_DB"] = "survey_test"

from pymongo import MongoClient

_client = MongoClient(os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/"))
_client.drop_database("survey_test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import app as app_module


@pytest.fixture(scope="session", autouse=True)
def clean_db():
    yield
    app_module.client.drop_database("survey_test")


@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture()
def db():
    return app_module.db
