from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter(prefix="/api/users")


@app.get("/health")
def health():
    return {"ok": True}


@router.get("/{user_id}")
async def get_user(user_id: int):
    return {"id": user_id}


@router.post("")
async def create_user(user: dict):
    return user


@router.api_route("/{user_id:int}/sync", methods=["PUT", "patch"])
async def sync_user(user_id: int):
    return None


@app.get(path="/items/{item_id}", response_model=dict)
def get_item(item_id: str):
    return {}


@app.on_event("startup")
def startup():
    pass
