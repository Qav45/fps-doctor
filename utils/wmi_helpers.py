def get_wmi_client():
    """Return wmi.WMI() or None if unavailable."""
    try:
        import wmi
        return wmi.WMI()
    except Exception:
        return None


def wmi_query(wmi_client, wql, fields=None):
    """Execute WQL query, return list of dicts. Returns [] on error."""
    if wmi_client is None:
        return []
    try:
        results = wmi_client.query(wql)
        output = []
        for item in results:
            if fields:
                row = {}
                for f in fields:
                    try:
                        row[f] = getattr(item, f, None)
                    except Exception:
                        row[f] = None
                output.append(row)
            else:
                # Return all available properties
                row = {}
                try:
                    for prop in item.properties:
                        try:
                            row[prop] = getattr(item, prop, None)
                        except Exception:
                            row[prop] = None
                except Exception:
                    pass
                output.append(row)
        return output
    except Exception:
        return []
