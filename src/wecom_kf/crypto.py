"""WeChat Customer Service signed AES-CBC envelope, using cryptography.

Protocol: https://developer.work.weixin.qq.com/document/path/90968
SHA-1 and the key-derived IV are mandated by this external protocol, not a new
general-purpose encryption design. Authenticate before decrypting any payload.
"""

import base64
import hashlib
import hmac
import re
import struct

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from defusedxml import ElementTree


class InvalidCallback(ValueError):
    """Untrusted callback failed validation; do not echo raw input to logs."""


def xml_field(root, name: str, *, required: bool = True) -> str:
    nodes = root.findall(name)
    if len(nodes) != 1 or nodes[0].text is None or len(nodes[0]):
        if not required and not nodes:
            return ""
        raise InvalidCallback("Invalid XML field")
    return nodes[0].text


def parse_xml(data: bytes):
    try:
        root = ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        if root.tag != "xml" or sum(1 for _ in root.iter()) > 100:
            raise InvalidCallback("Invalid XML envelope")
        return root
    except Exception:
        raise InvalidCallback("Invalid XML envelope") from None


class CallbackCrypto:
    def __init__(self, corp_id: str, token: str, aes_key: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", corp_id):
            raise ValueError("WECOM_CORP_ID is missing or invalid")
        if not re.fullmatch(r"[A-Za-z0-9]{3,32}", token):
            raise ValueError("Callback Token must contain 3-32 letters/digits")
        if not re.fullmatch(r"[A-Za-z0-9+/]{43}", aes_key):
            raise ValueError("EncodingAESKey must be 43 base64 characters")
        self._key = base64.b64decode(aes_key + "=", validate=True)
        if len(self._key) != 32:
            raise ValueError("EncodingAESKey must decode to 32 bytes")
        self._corp_id = corp_id.encode("utf-8")
        self._token = token
        self.key_id = hashlib.sha256(self._key).hexdigest()[:16]

    def decrypt(self, encrypted: str, signature: str, timestamp: str, nonce: str) -> bytes:
        if (not re.fullmatch(r"[0-9a-f]{40}", signature)
                or not re.fullmatch(r"[0-9]{1,16}", timestamp)
                or not nonce or len(nonce) > 128 or len(encrypted) > 65536):
            raise InvalidCallback("Invalid callback")
        expected = hashlib.sha1("".join(sorted([self._token, timestamp, nonce, encrypted])).encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidCallback("Invalid callback")
        try:
            ciphertext = base64.b64decode(encrypted, validate=True)
            if not ciphertext or len(ciphertext) % 16:
                raise ValueError("Invalid block length")
            decryptor = Cipher(algorithms.AES(self._key), modes.CBC(self._key[:16])).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            # WeCom uses a 32-byte padding block, independent of AES's 16-byte block.
            unpadder = padding.PKCS7(256).unpadder()
            plain = unpadder.update(padded) + unpadder.finalize()
            if len(plain) < 20:
                raise ValueError("Short envelope")
            size = struct.unpack("!I", plain[16:20])[0]
            if size > len(plain) - 20:
                raise ValueError("Invalid message length")
            message, receive_id = plain[20:20 + size], plain[20 + size:]
            if not hmac.compare_digest(receive_id, self._corp_id):
                raise ValueError("Wrong receive ID")
            return message
        except Exception:
            raise InvalidCallback("Invalid callback") from None
