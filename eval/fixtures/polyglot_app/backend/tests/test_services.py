import pytest

from backend.decorators import CALL_LOG
from backend.handlers import call_service, dispatch
from backend.services import UserService
from backend.user_repo import UserRepo


def make_service() -> UserService:
    return UserService(UserRepo())


class TestUserService:
    def test_create_user_assigns_ids(self):
        service = make_service()
        first = service.create_user("ada")
        second = service.create_user("grace")
        assert (first.id, second.id) == (1, 2)
        assert CALL_LOG[-1] == "create_user"

    def test_get_user_returns_none_when_missing(self):
        assert make_service().get_user(42) is None


def test_user_repo_rejects_empty_name():
    service = make_service()
    with pytest.raises(ValueError):
        service.create_user("")


def test_find_by_name():
    repo = UserRepo()
    UserService(repo).create_user("linus")
    assert repo.find_by_name("linus").id == 1


def test_dispatch_and_getattr():
    service = make_service()
    dispatch("create", service, {"name": "ada"})
    assert dispatch("list", service, {}) == [{"id": 1, "name": "ada"}]
    assert len(call_service(service, "list_users")) == 1
