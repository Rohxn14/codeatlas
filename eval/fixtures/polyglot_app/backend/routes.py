from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .handlers import dispatch
from .models import user_to_dict
from .services import UserService
from .user_repo import UserRepo

router = APIRouter(prefix="/api")
service = UserService(UserRepo())


class NewUser(BaseModel):
    name: str


@router.get("/users")
def list_users() -> list[dict]:
    return dispatch("list", service, {})


@router.get("/users/{id}")
def get_user(id: int) -> dict:
    user = service.get_user(id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user_to_dict(user)


@router.post("/users")
def create_user(body: NewUser) -> dict:
    return dispatch("create", service, {"name": body.name})
