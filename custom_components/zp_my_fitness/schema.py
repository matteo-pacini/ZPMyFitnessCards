"""The schema library of the running Home Assistant.

Newer Home Assistant releases validate flows and websocket messages with
probatio, older ones with voluptuous, and each only accepts its own schemas.
"""

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol

__all__ = ["vol"]
