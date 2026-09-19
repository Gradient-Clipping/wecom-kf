import unittest
from unittest.mock import Mock, patch

from wecom_kf.service_catalog import SERVICES, register_service, registered_services, service_factory
from wecom_kf.service_registry import ServiceRegistry, UnknownService


class ServiceRegistryTests(unittest.TestCase):
    def test_existing_catalog_keeps_educoder_contract(self):
        self.assertEqual(SERVICES["educoder"], "头歌")
        self.assertEqual(
            registered_services(),
            [{"code": "educoder", "name": "头歌"}, {"code": "shuori", "name": "朔日"}],
        )
        self.assertTrue(callable(service_factory("educoder")))

    def test_adapter_is_lazy_and_cached(self):
        settings = object()
        adapter = object()
        with patch("wecom_kf.service_registry.create_service", return_value=adapter) as create:
            registry = ServiceRegistry(settings)
            self.assertIs(registry.get("educoder"), adapter)
            self.assertIs(registry.get("educoder"), adapter)
        create.assert_called_once_with("educoder", settings)

    def test_override_supports_worker_dependency_injection(self):
        adapter = object()
        registry = ServiceRegistry(object(), overrides={"educoder": adapter})
        self.assertIs(registry.for_binding({"service": "educoder"}), adapter)
        self.assertIs(registry.for_binding({}), adapter)

    def test_unknown_service_is_rejected(self):
        registry = ServiceRegistry(object())
        with self.assertRaises(UnknownService):
            registry.get("missing")
        with self.assertRaises(UnknownService):
            registry.for_binding({"service": "missing"})

    def test_registration_is_idempotent_only_for_same_descriptor(self):
        code = "registry-test"
        factory = Mock()
        try:
            register_service(code, "测试服务", factory)
            register_service(code, "测试服务", factory)
            with self.assertRaises(ValueError):
                register_service(code, "另一个名称", factory)
        finally:
            # This test-only descriptor must not leak into admin metadata.
            SERVICES.pop(code, None)
            from wecom_kf import service_catalog
            service_catalog._FACTORIES.pop(code, None)


if __name__ == "__main__":
    unittest.main()
