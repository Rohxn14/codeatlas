from .decorators import logged
from .models import User
from .user_repo import UserRepo


class UserService:
    def __init__(self, repo: UserRepo) -> None:
        self.repo = repo

    def list_users(self) -> list[User]:
        return self.repo.all()

    def get_user(self, user_id: int) -> User | None:
        return self.repo.get(user_id)

    @logged
    def create_user(self, name: str) -> User:
        user = User(id=self._next_id(), name=name)
        self.repo.save(user.id, user)
        return user

    def _next_id(self) -> int:
        return len(self.repo.all()) + 1
