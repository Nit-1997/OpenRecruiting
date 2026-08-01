"""Tier-1 ATS provider: Knit unified APIs (api.getknit.dev).

transport.py  single HTTP choke point (auth headers, retry, error mapping)
auth.py       platform calls: auth.createSession, integration.details/deactivate
apis/         category groups (jobs/, candidates/) implementing core ports
webhook/      X-Knit-Signature verification + event handlers
adapters/     phase 2 — Knit-wire-specific translation
"""
