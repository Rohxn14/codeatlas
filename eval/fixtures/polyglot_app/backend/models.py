from dataclasses import dataclass


@dataclass
class User:
    id: int
    name: str


def user_to_dict(user: User) -> dict:
    return {"id": user.id, "name": user.name}
