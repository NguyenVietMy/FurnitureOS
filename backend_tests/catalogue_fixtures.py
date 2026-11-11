"""Frozen Product inputs for historical fixed-ID geometry transcripts.

These use the unchanged original published records and real Mesh dimensions.
Configured expansion behavior is exercised against the complete Catalogue.
"""
from functools import lru_cache
from api.catalogue import StaticCatalogue
from api.catalogue.providers.abo import abo_entries
from api.catalogue.providers.living import reviewed_entries


@lru_cache
def original_published_catalogue():
    return StaticCatalogue('CONTROLLED-original-published-23', reviewed_entries(abo_entries()))
