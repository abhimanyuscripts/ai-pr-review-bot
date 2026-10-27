import unittest

from reviewer.signals import FileChange, added_lines, compute_signals

AUTH_PATCH = """@@ -10,3 +10,6 @@ def login(user):
     check(user)
+    SECRET_KEY = "super-secret-value-123"
+    token = make(user)
     return True
+# done"""


class AddedLinesTest(unittest.TestCase):
    def test_tracks_new_file_line_numbers(self):
        self.assertEqual(
            added_lines(AUTH_PATCH),
            [(11, '    SECRET_KEY = "super-secret-value-123"'), (12, "    token = make(user)"), (14, "# done")],
        )

    def test_handles_missing_patch(self):
        self.assertEqual(added_lines(None), [])


class ComputeSignalsTest(unittest.TestCase):
    def test_docs_only_change_is_low_risk(self):
        s = compute_signals([FileChange("README.md", additions=300, deletions=10, patch="@@ -1 +1 @@\n+hi")])
        self.assertTrue(s.docs_only)
        self.assertEqual((s.score, s.level), (0, "low"))

    def test_hardcoded_secret_forces_high(self):
        s = compute_signals([FileChange("app/auth.py", additions=3, deletions=0, patch=AUTH_PATCH)])
        self.assertEqual(s.possible_secrets, ["app/auth.py:11"])
        self.assertEqual(s.level, "high")
        self.assertIn("authentication / security", s.sensitive)

    def test_code_without_tests_is_flagged(self):
        s = compute_signals([FileChange("app/service.py", additions=40, deletions=5, patch="@@ -1 +1 @@\n+x = 1")])
        self.assertIn("code changed without any test changes", s.reasons)
        self.assertEqual(s.level, "low")  # 15 points: noticed, but not enough on its own

    def test_tests_are_recognised(self):
        s = compute_signals(
            [
                FileChange("app/service.py", additions=40, deletions=5, patch="@@ -1 +1 @@\n+x = 1"),
                FileChange("tests/test_service.py", additions=30, deletions=0, patch="@@ -1 +1 @@\n+y = 2"),
            ]
        )
        self.assertEqual(s.test_files, ["tests/test_service.py"])
        self.assertNotIn("code changed without any test changes", s.reasons)

    def test_lockfiles_are_skipped_not_scanned(self):
        s = compute_signals(
            [FileChange("package-lock.json", additions=900, deletions=0, patch='@@ -1 +1 @@\n+"token": "abcdefgh"')]
        )
        self.assertEqual(s.skipped_files, ["package-lock.json"])
        self.assertEqual(s.possible_secrets, [])

    def test_large_sensitive_change_is_high(self):
        s = compute_signals(
            [
                FileChange("db/migrations/0042_users.sql", additions=400, deletions=150, patch="@@ -1 +1 @@\n+ALTER"),
                FileChange(".github/workflows/deploy.yml", additions=20, deletions=2, patch="@@ -1 +1 @@\n+on: push"),
            ]
        )
        self.assertEqual(s.level, "high")
        self.assertIn("CI/CD workflow", s.sensitive)
        self.assertIn("database schema / migration", s.sensitive)


if __name__ == "__main__":
    unittest.main()
