"""Module-level registry mapping charge_point_id → ChargePoint16 instance."""

_registry: dict = {}


def register(cp_id: str, cp) -> None:
    _registry[cp_id] = cp


def unregister(cp_id: str) -> None:
    _registry.pop(cp_id, None)


def get(cp_id: str):
    return _registry.get(cp_id)


def all_ids() -> list[str]:
    return list(_registry.keys())
