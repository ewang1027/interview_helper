"""Sandboxed code execution service.

This service runs untrusted code. It is deliberately the smallest thing in the repo:
no database client, no LLM client, no outbound network. Everything it needs arrives
in the request body and everything it returns is in the response.

Phase 0 ships the health surface; the executor itself lands in Phase 2.
"""

__version__ = "0.1.0"
