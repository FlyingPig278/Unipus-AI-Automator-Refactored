import tempfile
import unittest
from pathlib import Path


class EnvUtilsTests(unittest.TestCase):
    def test_reset_env_flag_if_true_rewrites_true_value_once(self):
        from src.env_utils import reset_env_flag_if_true

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                'U_USERNAME="alice"\nREFRESH_TASK_QUEUE="True"\nFORCE_AI="False"\n',
                encoding="utf-8",
            )

            changed = reset_env_flag_if_true(env_file, "REFRESH_TASK_QUEUE")

            self.assertTrue(changed)
            self.assertEqual(
                env_file.read_text(encoding="utf-8"),
                'U_USERNAME="alice"\nREFRESH_TASK_QUEUE="False"\nFORCE_AI="False"\n',
            )

    def test_reset_env_flag_if_true_leaves_false_value_unchanged(self):
        from src.env_utils import reset_env_flag_if_true

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            original = "REFRESH_TASK_QUEUE=False\n"
            env_file.write_text(original, encoding="utf-8")

            changed = reset_env_flag_if_true(env_file, "REFRESH_TASK_QUEUE")

            self.assertFalse(changed)
            self.assertEqual(env_file.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
