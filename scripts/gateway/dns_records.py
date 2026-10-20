"""Expose readiness-scoped DNS generation through the host helper namespace."""

from gateway.development.dns_records import generate_dns_records

__all__ = ["generate_dns_records"]
