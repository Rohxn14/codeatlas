class Order:
    def __init__(self, items=None):
        self.items = items or []

    def total(self):
        return len(self.items)


def make_order():
    return Order()
