import math


def format_bytes(size_bytes: int) -> str:
    """
    Converts bytes to a human-readable format (KB, MB, GB).

    Args:
        size_bytes: The size in bytes.

    Returns:
        A string representing the size in a human-readable format.
    """
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"
