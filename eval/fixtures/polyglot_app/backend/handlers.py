from .models import user_to_dict
from .services import UserService


def handle_list(service: UserService, payload: dict) -> list[dict]:
    return [user_to_dict(u) for u in service.list_users()]


def handle_create(service: UserService, payload: dict) -> dict:
    return user_to_dict(service.create_user(payload["name"]))


HANDLERS = {"list": handle_list, "create": handle_create}


def dispatch(name: str, service: UserService, payload: dict):
    return HANDLERS[name](service, payload)


def call_service(service: UserService, method_name: str):
    return getattr(service, method_name)()
