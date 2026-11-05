"""Source adapters. Each takes its config entry from sources.yaml and a Context, and returns RawEvents."""

from . import acs, aisa, html, ical, jsonld
from .base import Context

KINDS = {
    "jsonld": jsonld.collect,
    "acs": acs.collect,
    "aisa": aisa.collect,
    "ical": ical.collect,
    "html": html.collect,
}

__all__ = ["KINDS", "Context"]
