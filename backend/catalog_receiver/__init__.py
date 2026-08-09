"""Deterministic local catalog data receiver."""

from backend.catalog_receiver.models import ReceiverError
from backend.catalog_receiver.readers import read_source

__all__ = ["ReceiverError", "read_source"]
