"""Reviewed local publication overlay. A proposal is never eligibility."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .abo import LivingCandidateCatalogue, StrictModel, seed_catalogue, entry_from_manifest, asset_manifest, ROOT
from ..contract import CatalogueEntry

PROFILE_PATH = Path(__file__).with_name('abo-living-candidates.json')
REVIEWED_PATH = Path(__file__).with_name('abo-living-reviewed.json')


class RuntimeFile(StrictModel):
    file: str = Field(pattern=r'^(?:asset-manifest\.json|lod[012]\.(?:bin|gltf)|textures/[a-zA-Z0-9_.-]+\.ktx2)$')
    bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class ReviewedEntry(StrictModel):
    productId: str = Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    rooms: tuple[Literal['living-room'], ...] = Field(min_length=1, max_length=1)
    privateStyleIds: tuple[str, ...] = Field(min_length=1, max_length=5)
    files: tuple[RuntimeFile, ...] = Field(min_length=8, max_length=64)


class ReviewedLiving(StrictModel):
    schemaVersion: Literal[1]
    version: Literal['abo-living-reviewed-v1']
    profileSha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviewActor: Literal['owner', 'agent']
    reviewEvidenceSha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    entries: tuple[ReviewedEntry, ...] = Field(min_length=5, max_length=8)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({e.productId for e in self.entries}) != len(self.entries):
            raise ValueError('Duplicate reviewed Product')
        raw = PROFILE_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.profileSha256:
            raise ValueError('Living profile changed')
        profile = LivingCandidateCatalogue.model_validate_json(raw)
        records = {p.productId: p for p in profile.products}
        known = {s.id for s in profile.styleVocabulary.styles}
        for e in self.entries:
            if e.productId not in records or not set(e.privateStyleIds) <= known or len(set(e.privateStyleIds)) != len(e.privateStyleIds):
                raise ValueError('Unknown reviewed Product or Style')
        if {records[e.productId].category for e in self.entries} != {'sofa','table','chair','rug','lamp'}:
            raise ValueError('Incomplete living seed')
        styles = [set().union(*(set(e.privateStyleIds) for e in self.entries if records[e.productId].category == category)) for category in ('sofa','table','chair')]
        if not set.intersection(*styles):
            raise ValueError('All three anchors need a common supported Style')
        return self


def reviewed_entries(base: tuple[CatalogueEntry, ...]) -> tuple[CatalogueEntry, ...]:
    """Fail closed to bedroom20 if an absent/incomplete publication is encountered.

    Node promotion reopens raw sources and native tools. Runtime verifies the
    exact closed installed inventory (or the packaged manifest during API-only
    delivery), profile identity, dimensions and tags without shipping originals.
    """
    if not REVIEWED_PATH.is_file():
        return base
    try:
        overlay = ReviewedLiving.model_validate_json(REVIEWED_PATH.read_bytes())
        raw = PROFILE_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != overlay.profileSha256:
            raise ValueError('Living profile changed')
        profile = LivingCandidateCatalogue.model_validate_json(raw)
        records = {p.productId: p for p in profile.products}
        known = {s.id for s in profile.styleVocabulary.styles}
        selected = []
        for e in overlay.entries:
            if e.productId not in records or len(set(e.privateStyleIds)) != len(e.privateStyleIds) or not set(e.privateStyleIds) <= known:
                raise ValueError('Unknown reviewed identity or Style')
            files = {f.file: f for f in e.files}
            if len(files) != len(e.files) or 'asset-manifest.json' not in files:
                raise ValueError('Invalid runtime inventory')
            directory = ROOT / 'public' / 'products' / e.productId
            if directory.exists():
                actual = {f.relative_to(directory).as_posix() for f in directory.rglob('*') if f.is_file()}
                if actual != set(files) or directory.is_symlink():
                    raise ValueError('Runtime file union changed')
                for f in e.files:
                    target = directory / f.file
                    if target.is_symlink() or target.parent.is_symlink():
                        raise ValueError('Linked runtime path')
                    data = target.read_bytes()
                    if len(data) != f.bytes or hashlib.sha256(data).hexdigest() != f.sha256:
                        raise ValueError('Runtime file changed')
            else:
                from .abo import BUNDLED_MANIFEST_DIR
                data = (BUNDLED_MANIFEST_DIR / f'{e.productId}.json').read_bytes()
                pin = files['asset-manifest.json']
                if len(data) != pin.bytes or hashlib.sha256(data).hexdigest() != pin.sha256:
                    raise ValueError('Packaged manifest changed')
            entry = entry_from_manifest(records[e.productId], asset_manifest(e.productId), room_types=e.rooms, private_style_ids=e.privateStyleIds, curated_on=profile.curatedOn)
            selected.append(entry)
        if {e.product.category for e in selected} != {'sofa', 'table', 'chair', 'rug', 'lamp'}:
            raise ValueError('Incomplete living seed')
        if not any(set(s.private_style_ids) & set(t.private_style_ids) & set(c.private_style_ids) for s in selected if s.product.category == 'sofa' for t in selected if t.product.category == 'table' for c in selected if c.product.category == 'chair'):
            raise ValueError('Anchors lack a common Style')
        result = {e.product.id: e for e in base}
        legacy_records = {p.productId: p for p in seed_catalogue().products}
        for entry in selected:
            old = result.get(entry.product.id)
            if old:
                if records[entry.product.id] != legacy_records[entry.product.id]:
                    raise ValueError('Legacy source metadata changed')
                entry = CatalogueEntry(old.product.model_copy(update={'roomTypes': (*old.product.roomTypes, 'living-room')}), tuple(dict.fromkeys((*old.private_style_ids, *entry.private_style_ids))), (('bedroom', old.private_style_ids), ('living-room', entry.private_style_ids)))
            result[entry.product.id] = entry
        return tuple(result.values())
    except (ValueError, OSError, KeyError):
        return base
