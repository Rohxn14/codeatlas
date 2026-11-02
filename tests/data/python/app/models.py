"""User models and services."""

import functools


class Repository:
    """Stores users."""

    def save(self, user):
        return user


class UserService(Repository, metaclass=Meta):
    """Business logic for users."""

    class Config:
        strict = True

        def load(self):
            return {}

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    @property
    def name(self) -> str:
        """The service name."""
        return "users"

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @staticmethod
    def version() -> int:
        return 2

    @classmethod
    def create(cls) -> "UserService":
        return cls(Repository())

    @functools.lru_cache(maxsize=None)
    async def fetch(self, user_id: int,
                    *, fresh: bool = False) -> dict:  # one call per user
        def build(row):
            return dict(row)

        return build({"id": user_id})


def helper():
    pass


def helper(value):
    pass
