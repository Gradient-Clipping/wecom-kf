"""Resolve customer-service adapters by their persisted service code."""

from .service_catalog import SERVICES, create_service


class UnknownService(ValueError):
    """Raised when a binding or job refers to an unavailable service."""


class ServiceRegistry:
    """Lazy, process-local adapter registry.

    The database stores only a service code.  This class is the single place
    that turns that code into an adapter, and caches one adapter per code for
    the lifetime of a worker.  ``overrides`` is intended for tests and for the
    existing Worker(service=...) dependency-injection hook.
    """

    def __init__(self, settings, *, overrides=None):
        self.settings = settings
        self._instances = {}
        self._overrides = dict(overrides or {})

    def get(self, code):
        if not isinstance(code, str) or code not in SERVICES:
            raise UnknownService(f"Unknown service: {code}")
        if code in self._overrides:
            return self._overrides[code]
        if code not in self._instances:
            self._instances[code] = create_service(code, self.settings)
        return self._instances[code]

    def for_binding(self, binding, *, default="educoder"):
        """Resolve a binding's service, using the legacy default if absent."""
        code = (binding or {}).get("service") or default
        return self.get(code)

    def available(self, codes=None):
        """Return instantiated adapters for the requested registered codes."""
        return {code: self.get(code) for code in (codes or SERVICES) if code in SERVICES}

