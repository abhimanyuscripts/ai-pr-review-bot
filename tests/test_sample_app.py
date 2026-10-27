import unittest

from sample_app.auth import UserStore


class UserStoreTest(unittest.TestCase):
    def test_register_and_login(self):
        store = UserStore()
        store.register("asha", "correct horse battery")
        self.assertTrue(store.login("asha", "correct horse battery"))
        self.assertFalse(store.login("asha", "wrong password"))
        self.assertFalse(store.login("nobody", "correct horse battery"))

    def test_rejects_short_password(self):
        with self.assertRaises(ValueError):
            UserStore().register("asha", "short")

    def test_rejects_duplicate_user(self):
        store = UserStore()
        store.register("asha", "correct horse battery")
        with self.assertRaises(ValueError):
            store.register("asha", "another long password")


if __name__ == "__main__":
    unittest.main()
