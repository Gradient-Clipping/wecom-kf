"""Registered customer services and their lazy adapter factories.

The catalog is deliberately small and dependency free.  Service switches are
stored in the database, while adapters are created by :mod:`service_registry`.
Keeping the factory here gives new integrations one stable registration point
without making the conversation or worker code import a concrete service.
"""

# Kept as a mapping for backwards compatibility with Store and the admin
# metadata endpoints.  Insertion order is part of the customer-facing menu.
SERVICES = {}
SERVICE_DEFAULTS = {}
_FACTORIES = {}


def register_service(code, name, factory, *, enabled_by_default=True):
    """Register a service descriptor and a lazy adapter factory.

    ``factory`` receives the application settings and returns an adapter.  A
    factory is intentionally not called during import, which keeps optional
    integrations from making the core process import their dependencies.
    Re-registering the same code is allowed only when the descriptor is
    unchanged; this makes module reloads idempotent while preventing a plugin
    from silently replacing an enabled service.
    """
    if not isinstance(code, str) or not code or len(code) > 32 or not code.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid service code")
    if not isinstance(name, str) or not name or len(name) > 128:
        raise ValueError("Invalid service name")
    if not callable(factory):
        raise TypeError("Service factory must be callable")
    old_name = SERVICES.get(code)
    old_factory = _FACTORIES.get(code)
    if old_name is not None and (old_name != name or old_factory is not factory):
        raise ValueError(f"Service already registered: {code}")
    SERVICES[code] = name
    SERVICE_DEFAULTS[code] = bool(enabled_by_default)
    _FACTORIES[code] = factory
    return factory


def service_factory(code):
    """Return the registered factory for *code*, or raise a stable error."""
    try:
        return _FACTORIES[code]
    except KeyError:
        raise KeyError(f"Unknown service: {code}") from None


def create_service(code, settings):
    """Instantiate one adapter through its registered lazy factory."""
    return service_factory(code)(settings)


def _educoder_factory(settings):
    # Import lazily so callers can inspect the catalog without loading the
    # large EduCoder client or its optional dependencies.
    from .educoder_service import EduCoderService
    return EduCoderService(settings)


register_service("educoder", "头歌", _educoder_factory)


def _shuori_factory(settings):
    # The adapter itself keeps the optional Sower runtime lazy.
    from .suori_service import ShuoriService
    return ShuoriService(
        settings,
        root=getattr(settings, "shuori_runtime_root", None),
        grading_mode=getattr(settings, "shuori_grading_mode", "full_score"),
        submit=getattr(settings, "shuori_submit_enabled", False),
    )


register_service("shuori", "朔日", _shuori_factory, enabled_by_default=False)


def registered_services():
    """Public descriptors for implemented services only; never infer adapter support."""
    return [{"code": code, "name": name} for code, name in SERVICES.items()]


def available(state):
    return state.get("available_services", registered_services())
