"""Shared slowapi Limiter instance, keyed by remote IP address.

Must be attached to app.state.limiter, and RateLimitExceeded must be
registered with app.add_exception_handler + SlowAPIMiddleware in main.py,
before any route decorated with @limiter.limit(...) works.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
