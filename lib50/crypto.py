import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from ._errors import InvalidSignatureError

def load_public_key(pem_str):
    return serialization.load_pem_public_key(pem_str, backend=default_backend())


def load_private_key(pem_str, password=None):
    return serialization.load_pem_private_key(pem_str, password=password, backend=default_backend())


def verify(payload, signature, public_key):
    """
    Verify payload using (base64 encoded) signature and verification key. verification_key should be obtained from load_public_key
    Uses RSA-PSS with SHA-512 and maximum salt length.
    The corresponding openssl command to create signatures that this function can verify is:

    openssl dgst -sha512 -sigopt rsa_padding_mode:pss -sigopt rsa_pss_saltlen:-2 -sign <PRIVATE_KEY> <PAYLOAD> | openssl base64 -A

    returns a boolean that is true iff the payload could be verified
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
    return base64.b64encode(
        private_key.sign(data=payload,
                         padding=padding.PSS(
                             mgf=padding.MGF1(hashes.SHA512()),
                             salt_length=padding.PSS.MAX_LENGTH),
                         algorithm=hashes.SHA512()))
