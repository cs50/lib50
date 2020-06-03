"""An API for verifying signed payloads such as check50 results."""

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from ._errors import InvalidSignatureError

def load_public_key(pem_str):
    """
    Load a public key from a PEM string.

    "PEM is an encapsulation format, meaning keys in it can actually be any of several different key types.
    However these are all self-identifying, so you don’t need to worry about this detail.
    PEM keys are recognizable because they all begin with
    ``-----BEGIN {format}-----`` and end with ``-----END {format}-----``."

    - source: https://cryptography.io/en/latest/hazmat/primitives/asymmetric/serialization/#pem

    :param pem_str: the public key to load in PEM format
    :type pem_str: str
    :return: a key from ``cryptography.hazmat``
    :type: One of RSAPrivateKey, DSAPrivateKey, DHPrivateKey, or EllipticCurvePrivateKey
    """
    return serialization.load_pem_public_key(pem_str, backend=default_backend())


def load_private_key(pem_str, password=None):
    """
    Load a private key from a PEM string.

    "PEM is an encapsulation format, meaning keys in it can actually be any of several different key types.
    However these are all self-identifying, so you don’t need to worry about this detail.
    PEM keys are recognizable because they all begin with
    ``-----BEGIN {format}-----`` and end with ``-----END {format}-----``."

    - source: https://cryptography.io/en/latest/hazmat/primitives/asymmetric/serialization/#pem

    :param pem_str: the private key to load in PEM format
    :type pem_str: str
    :param password: a password to decode the pem_str
    :type password: str, optional
    :return: a key from ``cryptography.hazmat``
    :type: One of RSAPrivateKey, DSAPrivateKey, DHPrivateKey, or EllipticCurvePrivateKey
    """
    return serialization.load_pem_private_key(pem_str, password=password, backend=default_backend())


def verify(payload, signature, public_key):
    """
    Verify payload using (base64 encoded) signature and verification key. public_key should be obtained from load_public_key
    Uses RSA-PSS with SHA-512 and maximum salt length.
    The corresponding openssl command to create signatures that this function can verify is:

    ::

        openssl dgst -sha512 -sigopt rsa_padding_mode:pss -sigopt rsa_pss_saltlen:-2 -sign <PRIVATE_KEY> <PAYLOAD> | openssl base64 -A

    :param payload: the payload
    :type payload: str
    :param signature: base64 encoded signature
    :type signature: bytes
    :param public_key: a public key from ``lib50.crypto.load_public_key``
    :return: True iff the payload could be verified
    :type: bool
    """
    try:
        public_key.verify(signature=base64.b64decode(signature),
                          data=payload,
                          padding=padding.PSS(
                                      mgf=padding.MGF1(hashes.SHA512()),
                                      salt_length=padding.PSS.MAX_LENGTH),
                          algorithm=hashes.SHA512())
    except InvalidSignature:
        return False

    return True


def sign(payload, private_key):
    """
    Sign a payload with a private key.

    :param payload: the payload
    :type payload: str
    :param private_key: a private key from ``lib50.crypto.load_private_key``
    :return: base64 encoded signature
    :type: bytes
    """
    return base64.b64encode(
        private_key.sign(data=payload,
                         padding=padding.PSS(
                             mgf=padding.MGF1(hashes.SHA512()),
                             salt_length=padding.PSS.MAX_LENGTH),
                         algorithm=hashes.SHA512()))
