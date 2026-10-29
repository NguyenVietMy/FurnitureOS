"""Version-one archival field map. Runtime authority is deliberately absent."""
from __future__ import annotations
from datetime import datetime
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator, field_validator
from .models import (ContractModel, RoomShell, RoomType, PlacementIntent, Placement,
                     SearchReport, Zone, ArrangementHistory, SolvedDesign, PositiveFinite)
from .capture_auth import CaptureError
from .domain import validate_placement
from .swaps import validate_fixed_pose_design
from .zones import derive_zones, ZoneDerivationError

POLICY = 'saved-until-deleted-v1'
MAX_SNAPSHOT_BYTES = 256 * 1024


class SaveRequest(ContractModel):
    sessionId: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    expectedVersion: int = Field(ge=1, le=2147483647, strict=True)
    idempotencyKey: str = Field(min_length=8, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    consent: Literal[True]
    policyVersion: Literal['saved-until-deleted-v1'] = POLICY

    @field_validator('consent', mode='before')
    @classmethod
    def literal_consent(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError('Explicit retention consent is required.')
        return value

    def identity_hash(self):
        return sha256(canonical([self.sessionId, self.expectedVersion, self.policyVersion])).hexdigest()


class SavedCapture(ContractModel):
    id: UUID
    confirmedRevision: int = Field(ge=1)
    roomHash: str = Field(pattern=r'^[a-f0-9]{64}$')


class SavedSnapshotV1(ContractModel):
    schemaVersion: Literal[1] = 1
    catalogueVersion: str = Field(min_length=1, max_length=128)
    status: Literal['solved'] = 'solved'
    roomType: RoomType
    clearanceWidthM: PositiveFinite = Field(ge=0.6, le=10)
    room: RoomShell
    intents: tuple[PlacementIntent, ...] = Field(min_length=1, max_length=20)
    placements: tuple[Placement, ...] = Field(min_length=1, max_length=20)
    search: SearchReport
    zones: tuple[Zone, ...] = Field(max_length=4096)
    arrangementHistory: ArrangementHistory | None = None
    capture: SavedCapture | None = None

    @model_validator(mode='after')
    def aligned(self):
        if self.capture is not None:
            from .capture_room import room_hash
            if self.room.id != 'capture-' + str(self.capture.id) or room_hash(self.room) != self.capture.roomHash:
                raise ValueError('Saved Capture association disagrees with the confirmed Room.')
        ids = [intent.id for intent in self.intents]
        if len(ids) != len(set(ids)) or len(self.intents) != len(self.placements):
            raise ValueError('Saved Placement instances must be complete and unique.')
        for intent, placement in zip(self.intents, self.placements, strict=True):
            if intent.id != placement.instanceId or intent.productId != placement.productId:
                raise ValueError('Saved Placement and Intent identities disagree.')
        zone_ids = [zone.id for zone in self.zones]
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError('Saved Zone identities must be unique.')
        for intent in self.intents:
            if intent.kind not in ('against', 'centred_on', 'in_corner', 'adjacent_to', 'facing', 'flanking', 'in_zone'):
                raise ValueError('Unsupported saved Intent kind.')
            if intent.referenceId is not None and (intent.referenceId not in ids or intent.referenceId == intent.id):
                raise ValueError('Saved Intent references an absent or self instance.')
            if intent.kind in ('adjacent_to', 'facing', 'flanking') and intent.referenceId is None:
                raise ValueError('Object-relative Intent requires a saved instance.')
            if intent.kind == 'in_zone' and intent.zoneId not in zone_ids:
                raise ValueError('Saved Intent references an absent Zone.')
        references = {intent.id: intent.referenceId for intent in self.intents}
        for start in ids:
            seen = set()
            while start is not None:
                if start in seen: raise ValueError('Saved Intent references contain a cycle.')
                seen.add(start); start = references[start]
        return self


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def snapshot_bytes(snapshot):
    data = canonical(snapshot.model_dump(mode='json'))
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise CaptureError('snapshot-limit', 'This Design exceeds the saved content limit.', 413)
    return data


def restore_snapshot(source, value, digest):
    if not isinstance(value, dict) or type(value.get('schemaVersion')) is not int or value['schemaVersion'] != 1:
        raise CaptureError('unsupported-schema', 'This saved Design format is unsupported.', 422)
    if value.get('catalogueVersion') != source.version:
        raise CaptureError('catalogue-changed', 'This saved Design needs its original Catalogue version.', 422)
    try:
        snapshot = SavedSnapshotV1.model_validate(value)
        if sha256(snapshot_bytes(snapshot)).hexdigest() != digest:
            raise ValueError('digest mismatch')
        if snapshot.zones and snapshot.zones != derive_zones(snapshot.room, snapshot.roomType).zones:
            raise ValueError('Zone derivation changed')
        products = tuple(source.get(intent.productId) for intent in snapshot.intents)
        if any(product is None or snapshot.roomType not in product.roomTypes for product in products):
            raise ValueError('ineligible Product')
        fits = tuple(validate_placement(product, snapshot.room, placement) for product, placement in zip(products, snapshot.placements, strict=True))
        provisional = SolvedDesign(status='solved', room=snapshot.room, intents=snapshot.intents,
            products=products, placements=snapshot.placements, fits=fits, search=snapshot.search,
            zones=snapshot.zones, arrangementHistory=snapshot.arrangementHistory)
        validated, failure = validate_fixed_pose_design(source, provisional, snapshot.clearanceWidthM)
        if validated is None:
            raise ValueError(failure.detail)
        return snapshot, validated
    except (ValueError, TypeError, ZoneDerivationError):
        raise CaptureError('corrupt-snapshot', 'This saved Design could not be validated. No preview was opened.', 422) from None


class SavedReceipt(ContractModel):
    status: Literal['saved'] = 'saved'
    id: UUID
    createdAt: datetime


class SavedSummary(ContractModel):
    id: UUID
    idempotencyKey: str
    createdAt: datetime
    roomType: RoomType
    captureId: UUID | None = None


class SavedList(ContractModel):
    items: tuple[SavedSummary, ...]
    nextCursor: str | None = None


class SavedRestore(ContractModel):
    id: UUID
    capture: SavedCapture | None
    roomType: RoomType
    design: SolvedDesign
