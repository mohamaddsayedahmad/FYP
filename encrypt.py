from cryptography.fernet import Fernet
import os

KEY_FILE = 'secret.key'

def load_key():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
    with open(KEY_FILE, 'rb') as f:
        return f.read()

def encrypt_data(data):
    cipher = Fernet(load_key())
    return cipher.encrypt(data.encode())

def decrypt_data(data):
    cipher = Fernet(load_key())
    return cipher.decrypt(data).decode()