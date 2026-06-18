import os


def load_soul() -> str:
    """Load soul.md from MEMORY_DIR. Returns empty string if file doesn't exist."""
    memory_dir = os.environ["BOYNTON_MEMORY_DIR"]
    soul_path = os.path.join(memory_dir, "SOUL.md")
    try:
        with open(soul_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def load_memory_index() -> str:
    """Load MEMORY.md from MEMORY_DIR. Returns empty string if file doesn't exist."""
    memory_dir = os.environ["BOYNTON_MEMORY_DIR"]
    memory_path = os.path.join(memory_dir, "MEMORY.md")
    try:
        with open(memory_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""

