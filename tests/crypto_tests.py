import pathlib
import unittest
import uuid

import lib50.crypto

KEY_DIRECTORY = pathlib.Path(__file__).absolute().parent / "crypto"

class TestCrypt(unittest.TestCase):
    def setUp(self):
        with open(KEY_DIRECTORY / "public.pem", "rb") as f:
            self.public_key = lib50.crypto.load_public_key(f.read())

        with open(KEY_DIRECTORY / "private.pem", "rb") as f:
            self.private_key = lib50.crypto.load_private_key(f.read())

    def test_sign_then_verify(self):
        payload = uuid.uuid4().hex.encode()
        signature = lib50.crypto.sign(payload, self.private_key)
        self.assertTrue(lib50.crypto.verify(payload, signature, self.public_key))

    def test_invalid_verify(self):
        payload1 = uuid.uuid4().hex.encode()
        payload2 = uuid.uuid4().hex.encode()

        # The probability that this loop even iterates once is basically 0
        while payload1 == payload2:
            payload2 = uuid.uuid4().hex.encode()

        signature1 = lib50.crypto.sign(payload1, self.private_key)
        self.assertFalse(lib50.crypto.verify(payload2, signature1, self.public_key))




