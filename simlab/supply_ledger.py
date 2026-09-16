"""Supply records. Quantity transitions are committed without yielding."""
from dataclasses import dataclass, field


@dataclass
class Demand:
    id: str
    sequence: int
    station: str
    iid: str
    created: float
    owner: str
    event: object = field(repr=False)
    quantity: int = 1
    fulfilled: int = 0
    completed: float | None = None


@dataclass
class Order:
    id: str
    sequence: int
    station: str
    iid: str
    created: float
    quantity: int
    sponsor: str
    reason: str
    unallocated: int = 0
    in_transit: int = 0
    received: int = 0

    def __post_init__(self):
        self.unallocated = self.quantity

    def dispatch(self, quantity):
        assert 0 < quantity <= self.unallocated
        self.unallocated -= quantity
        self.in_transit += quantity

    def receive(self, quantity):
        assert 0 < quantity <= self.in_transit
        self.in_transit -= quantity
        self.received += quantity

    def validate(self):
        assert self.quantity > 0
        assert min(self.unallocated, self.in_transit, self.received) >= 0
        assert self.quantity == self.unallocated + self.in_transit + self.received


@dataclass
class Shipment:
    id: str
    order: str
    route: str
    source: str
    destination: str
    iid: str
    parts: list
    departure: float
    arrival: float
    received: bool = False

    @property
    def quantity(self):
        return len(self.parts)
