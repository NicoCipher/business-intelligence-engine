"""
auth.py — Single-operator API-key authentication seam.

BIA is a single-operator system today. Every protected endpoint depends
on exactly one function, get_current_actor(), rather than checking a
key directly at each call site. When multi-user support is ever built,
only this function's internals change -- no route needs to be touched.
This is deliberately NOT a full auth system: no sessions, no RBAC, no
MFA. Those are real complexity this system doesn't need at solo-operator
scale, and building them now would be exactly the kind of premature
abstraction this project has consistently avoided elsewhere.

Configuration: BIA_API_KEY (env var).
  - Unset (default): auth is disabled entirely. Preserves today's open
    local-development behavior -- nothing breaks for anyone running BIA
    locally without configuring a key.
  - Set: every protected route requires a matching
    `Authorization: Bearer <key>` header, or the request is rejected
    with 401.

V1 is explicitly kept private (no public network exposure) per the
accepted security review -- this key is a defense-in-depth layer for
that boundary today, and becomes the primary boundary the moment
network isolation is ever lifted, with zero code changes required.
"""

import logging
import os

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

API_KEY = os.getenv("BIA_API_KEY", "")


class Actor:
    """
    The current request's identity. A single, fixed actor today --
    intentionally structured as an object (not just a bool) so that a
    future multi-user get_current_actor() can return real per-request
    identities without changing any call site's type expectations.
    """

    def __init__(self, id: str = "operator"):
        self.id = id

    def __repr__(self) -> str:
        return f"Actor(id={self.id!r})"


def get_current_actor(authorization: str | None = Header(default=None)) -> Actor:
    """
    FastAPI dependency. Validates the Authorization header against
    BIA_API_KEY and returns the current actor, or raises 401.

    If BIA_API_KEY is unset, this always succeeds without checking
    anything -- see module docstring for why that's the correct default
    rather than a security hole: it's an explicit, documented opt-in.
    """
    if not API_KEY:
        return Actor()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    provided = authorization.removeprefix("Bearer ").strip()
    if provided != API_KEY:
        logger.warning("Rejected request with invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    return Actor()
