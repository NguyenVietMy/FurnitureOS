"""Metadata-only discovery. Never assigns accepted Style/Room/access decisions."""
import argparse, hashlib, json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--metadata-file', required=True)
p.add_argument('--category', choices=['bed','nightstand','wardrobe','dresser','chair','sofa','table','rug','lamp'], required=True)
p.add_argument('--limit', type=int, default=50)
p.add_argument('--exclude-published', action='store_true')
a = p.parse_args()
assert 1 <= a.limit <= 50
raw = Path(a.metadata_file).read_bytes()
assert hashlib.sha256(raw).hexdigest() == '660f4d01bf817802c4fc664e848af12b72246efdb15324ad1d0d2bce33f54fe9'
root = Path(__file__).resolve().parents[2]
published = set()
if a.exclude_published:
    import sys
    sys.path.insert(0,str(root))
    from api.catalogue import catalogue
    published = {p.attribution.materialUrl.rsplit('/',1)[1][:-4] for p in catalogue.list()}
words = {'bed':('BED',),'nightstand':('NIGHTSTAND','BEDSIDE'),'wardrobe':('WARDROBE',),'dresser':('DRESSER','CHEST_OF_DRAWERS'),'chair':('CHAIR',),'sofa':('SOFA',),'table':('COFFEE_TABLE',),'rug':('RUG',),'lamp':('FLOOR_LAMP',)}
seen = set(); rows=[]
for line in raw.splitlines():
    r=json.loads(line); model=r.get('3dmodel_id')
    if not model or model in seen or model in published: continue
    names=r.get('item_name',[]); name=next((n['value'] for n in names if n.get('language_tag')=='en_US'),next((n['value'] for n in names if n.get('language_tag','').startswith('en')),model))
    types=[x['value'] for x in r.get('product_type',[])]
    text=(' '.join(types)+' '+name).upper().replace(' ','_')
    if not any(w in text for w in words[a.category]): continue
    seen.add(model)
    rows.append(dict(itemId=r['item_id'],modelId=model,displayName=name,proposedCategory=a.category,listingTypes=types,sourcePath=f'{model[-1]}/{model}.glb',sourceUrl=f'https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/{model[-1]}/{model}.glb',status='METADATA_PROPOSAL_REQUIRES_SELECTION_SOURCE_PIN_AND_MESH_REVIEW'))
print(json.dumps(dict(schemaVersion=1,metadataSha256=hashlib.sha256(raw).hexdigest(),category=a.category,totalUniqueMetadataMatches=len(rows),limit=a.limit,candidates=sorted(rows,key=lambda r:r['modelId'])[:a.limit],acceptedProducts=0),indent=2))
