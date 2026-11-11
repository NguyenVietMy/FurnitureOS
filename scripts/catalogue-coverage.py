"""Explicit unique Product and private coverage inventory; no readiness inference."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.catalogue import catalogue, CatalogueQuery
from api.room_policy import room_policy
from api.live_generation import candidate_window, reference_manifest, frozen_generation_configuration


def coverage(source=catalogue):
    products = source.list()
    matrix = []
    missing = []
    for room in ('bedroom', 'living-room'):
        policy = room_policy(room)
        for style in (f'style-{i:02}' for i in range(1, 6)):
            eligible = source.list(CatalogueQuery(room_type=room, private_style_id=style))
            window = candidate_window(eligible, policy)
            for category in ('bed','nightstand','wardrobe','dresser','sofa','table','chair','rug','lamp'):
                chosen = [p for p in eligible if p.category == category]
                row = dict(roomType=room, privateStyleId=style, category=category, count=len(chosen), productIds=sorted(p.id for p in chosen), windowProductIds=sorted(p.id for p in window if p.category == category), requiredAnchor=category in {c for _,c in policy.anchors}, access=[dict(productId=p.id,placementClass=p.placementClass,wallContactFaces=p.wallContactFaces,accessRegions=[a.model_dump() for a in p.accessRegions]) for p in chosen])
                matrix.append(row)
                if row['requiredAnchor'] and len(chosen) < 2:
                    missing.append(dict(roomType=room, privateStyleId=style, category=category, minimum=2, actual=len(chosen)))
    prompts = {}
    for room in ('bedroom','living-room'):
        try:
            config = frozen_generation_configuration(source,room)
            prompts[room] = dict(bytesByReference=config['promptContractBytesByReference'],candidateWindow=config['candidateWindow'],status='WITHIN_BYTE_BOUND')
        except ValueError as e:
            prompts[room] = dict(status='FAILED',detail=str(e))
    return dict(schemaVersion=1,catalogueVersion=source.version,uniqueProducts=len(products),productIds=sorted(p.id for p in products),targetUniqueProducts=300,countTargetMet=len(products)>=300,anchorCoverageMet=not missing,missingAnchorAlternatives=missing,matrix=matrix,promptAudit=prompts,ownerEvidenceStatus='UNRUN',providerEvidenceStatus='DEFERRED_TO_END_OF_PROJECT_UNRUN',physicalPhoneStatus='WAIVED_NOT_PASSED')


if __name__ == '__main__':
    print(json.dumps(coverage(),indent=2))
