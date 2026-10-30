from .models import User
from .repo import Repo as BaseRepo


class UserRepo(BaseRepo):
    def save(self, item_id: int, item: User) -> None:
        if not item.name:
            raise ValueError("name is required")
        super().save(item_id, item)

    def find_by_name(self, name: str) -> User | None:
        for user in self.all():
            if user.name == name:
                return user
        return None
