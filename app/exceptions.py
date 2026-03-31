class ConfigurationError(Exception):
    """Raised when task YAML is missing required fields or contains invalid values."""


class TemplateLoadError(Exception):
    """Raised when a DPI template JSON file is missing or malformed."""
