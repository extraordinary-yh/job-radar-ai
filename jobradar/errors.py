class AdapterError(Exception):
    """Raised when a source cannot be fetched or parsed. One source failing never stops the run."""
