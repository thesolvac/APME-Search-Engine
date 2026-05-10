"""
Standardised JSON response helpers.

Every API response has the shape:
    { "status": "success"|"error",
      "success": true|false,
      "message": str,
      "data": any          (success only, omitted when None)
      "details": any       (error only,   omitted when None)
    }

The duplicate boolean ``success`` field is kept for backward compatibility
with consumers that check ``res.success``.
The string ``status`` field allows strict equality checks: ``res.status === 'error'``.
"""

from flask import jsonify


def success(data=None, message: str = "OK", status: int = 200):
    """Return a 2xx JSON success response."""
    payload: dict = {"status": "success", "success": True, "message": message}
    if data is not None:
        payload["data"] = data
    return jsonify(payload), status


def error(message: str, status: int = 400, details=None):
    """Return a 4xx/5xx JSON error response."""
    payload: dict = {"status": "error", "success": False, "message": message}
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status
