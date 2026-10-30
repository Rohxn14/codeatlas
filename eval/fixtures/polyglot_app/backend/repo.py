class Repo:
    def __init__(self) -> None:
        self.items: dict[int, object] = {}

    def get(self, item_id: int):
        return self.items.get(item_id)

    def all(self) -> list:
        return list(self.items.values())

    def save(self, item_id: int, item: object) -> None:
        self.items[item_id] = item
