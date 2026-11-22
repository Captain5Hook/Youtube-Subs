"""
Credits and Author Integrity Manager
Protects the author attribution using encryption and passcode verification.
Passcode required for editing or removal: 0055
"""

import os
import sys
import json
import base64
import hashlib
import hmac

LOCK_FILE = "creator.lock"
SALT = b"yt_counter_secret_salt_v1"


def _derive_key(passcode: str) -> bytes:
    """Derive 32-byte encryption key from passcode using PBKDF2."""
    return hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), SALT, iterations=100_000)


def _keystream(key: bytes, length: int) -> bytes:
    """Generate deterministic keystream of given length from key."""
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(key + counter.to_bytes(4, "big")).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def _xor_crypt(data: bytes, key: bytes) -> bytes:
    """XOR encryption/decryption using keystream."""
    keystream = _keystream(key, len(data))
    return bytes(b ^ k for b, k in zip(data, keystream))


def create_lock_file(author_name: str, passcode: str = "0055", custom_message: str = None) -> None:
    """Creates an encrypted creator.lock file with passcode protection."""
    key = _derive_key(passcode)
    passcode_hash = hashlib.sha256(passcode.encode("utf-8") + SALT).hexdigest()

    display_text = custom_message or f"Created by {author_name}"
    payload = {
        "author": author_name,
        "display": display_text,
        "passcode_hash": passcode_hash,
    }

    raw_json = json.dumps(payload).encode("utf-8")
    encrypted_bytes = _xor_crypt(raw_json, key)
    signature = hmac.new(key, encrypted_bytes, hashlib.sha256).hexdigest()

    file_data = {
        "display_cache": base64.b64encode(display_text.encode("utf-8")).decode("utf-8"),
        "payload": base64.b64encode(encrypted_bytes).decode("utf-8"),
        "signature": signature,
        "passcode_hash": passcode_hash
    }

    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        json.dump(file_data, f, indent=2)


def verify_and_get_credit() -> str:
    """
    Called by bot.py to display the creator credit.
    Ensures creator.lock exists and has not been stripped or corrupted.
    """
    if not os.path.exists(LOCK_FILE):
        print("\n" + "=" * 60)
        print("❌ CRITICAL ERROR: 'creator.lock' file is missing!")
        print("This bot requires the creator verification file to run.")
        print("=" * 60 + "\n")
        sys.exit(1)

    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        cached_b64 = data.get("display_cache", "")
        display = base64.b64decode(cached_b64.encode("utf-8")).decode("utf-8")
        if not display:
            raise ValueError("Empty creator info.")
        return display
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ CRITICAL ERROR: 'creator.lock' is invalid or tampered! ({e})")
        print("=" * 60 + "\n")
        sys.exit(1)


def unlock_and_edit():
    """Interactive management CLI to edit or remove creator credit."""
    print("=" * 50)
    print("🔐 YouTube Sub Counter - Creator Lock Manager")
    print("=" * 50)

    if not os.path.exists(LOCK_FILE):
        print("No creator.lock found. Creating a new one...")
        entered_code = input("Enter new passcode (default 0055): ").strip() or "0055"
        author = input("Enter author name: ").strip() or "Captain5Hook"
        create_lock_file(author, entered_code)
        print(f"✅ Created creator.lock for '{author}'.")
        return

    # Verify existing lock
    with open(LOCK_FILE, "r", encoding="utf-8") as f:
        file_data = json.load(f)

    expected_hash = file_data.get("passcode_hash")
    input_code = input("Enter passcode to unlock: ").strip()
    input_hash = hashlib.sha256(input_code.encode("utf-8") + SALT).hexdigest()

    if input_hash != expected_hash:
        print("\n❌ ACCESS DENIED: Incorrect passcode! You cannot edit or remove this file.")
        sys.exit(1)

    print("\n✅ Passcode Accepted!")
    print("1. View current credits")
    print("2. Edit creator name / message")
    print("3. Change passcode")
    print("4. Remove lock file")
    print("5. Exit")

    choice = input("\nSelect an option (1-5): ").strip()

    if choice == "1":
        cached = base64.b64decode(file_data["display_cache"]).decode("utf-8")
        print(f"\nCurrent Credit: {cached}")

    elif choice == "2":
        new_name = input("Enter new creator name: ").strip()
        new_msg = input(f"Enter custom display message (Enter for 'Created by {new_name}'): ").strip()
        create_lock_file(new_name, input_code, new_msg if new_msg else None)
        print("✅ Creator credits updated successfully!")

    elif choice == "3":
        new_code = input("Enter new passcode: ").strip()
        cached = base64.b64decode(file_data["display_cache"]).decode("utf-8")
        create_lock_file(cached.replace("Created by ", ""), new_code, cached)
        print("✅ Passcode updated successfully!")

    elif choice == "4":
        confirm = input("Are you sure you want to remove creator.lock? (yes/no): ").strip().lower()
        if confirm == "yes":
            os.remove(LOCK_FILE)
            print("⚠️ 'creator.lock' removed. Note: bot.py requires this file to run.")
        else:
            print("Canceled.")

    else:
        print("Exiting.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--init":
        create_lock_file("Captain5Hook", "0055")
        print("Initialized creator.lock with passcode 0055.")
    else:
        unlock_and_edit()
