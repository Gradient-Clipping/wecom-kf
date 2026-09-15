"""Registered customer services; switches are stored separately from adapters."""

SERVICES = {"educoder": "头歌"}


def available(state):
    return state.get("available_services", [{"code": code, "name": name} for code, name in SERVICES.items()])
