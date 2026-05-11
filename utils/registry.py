import winreg


def read_reg(hive, path, name, default=None):
    """Read a single registry value, return default on any error."""
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except Exception:
        return default


def read_reg_dword(hive, path, name, default=0):
    """Read a DWORD registry value, return default on any error."""
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, reg_type = winreg.QueryValueEx(key, name)
            if reg_type in (winreg.REG_DWORD, winreg.REG_DWORD_BIG_ENDIAN, winreg.REG_QWORD):
                return int(value)
            return default
    except Exception:
        return default


def reg_key_exists(hive, path):
    """Return True if the registry key exists, False otherwise."""
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except Exception:
        return False


def list_reg_subkeys(hive, path):
    """Return list of subkey names under the given key. Returns [] on error."""
    subkeys = []
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            index = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, index)
                    subkeys.append(subkey_name)
                    index += 1
                except OSError:
                    break
    except Exception:
        pass
    return subkeys


def list_reg_values(hive, path):
    """Return dict of {name: value} for all values in a key."""
    values = {}
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                    values[name] = value
                    index += 1
                except OSError:
                    break
    except Exception:
        pass
    return values
