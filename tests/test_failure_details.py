import unittest

from wecom_kf.failure_details import exception_detail


class FailureDetailsTests(unittest.TestCase):
    def test_exception_message_is_bounded_and_redacted(self):
        error = RuntimeError("password=secret-token authorization=Bearer abc123 provider rejected")
        value = exception_detail(error, secrets=("secret-token",))
        self.assertIn("RuntimeError", value)
        self.assertIn("[已脱敏]", value)
        self.assertNotIn("secret-token", value)
        self.assertNotIn("abc123", value)


if __name__ == "__main__":
    unittest.main()
