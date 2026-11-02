import unittest

import pytest


@pytest.fixture
def user():
    return {"id": 1}


def test_create_user(user):
    assert user["id"] == 1


async def test_fetch():
    def test_inner():
        pass


def helper_for_tests():
    pass


class TestUserService:
    def test_save(self):
        pass

    def setup_method(self):
        pass

    class TestNested:
        def test_deep(self):
            pass


class UserCase(unittest.TestCase):
    def test_load(self):
        self.assertTrue(True)

    def testLegacyName(self):
        pass


class Helper:
    def test_not_collected(self):
        pass
