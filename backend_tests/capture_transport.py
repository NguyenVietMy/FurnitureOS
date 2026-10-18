"""Explicit controlled Supabase transport for OFFLINE boundary/browser proof only."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from threading import RLock
from uuid import UUID,uuid4
import httpx
from api.capture_auth import CaptureError,SupabaseSettings
from api.capture_repository import SupabaseCaptureRepository
from api.capture_models import CaptureDraft

OWNERS={"test-owner-a":"11111111-1111-1111-1111-111111111111","test-owner-b":"22222222-2222-2222-2222-222222222222"}
class ControlledSupabase:
    def __init__(self):
        self.settings=SupabaseSettings("https://capture-test.invalid","test-public","test-service")
        self.rows={};self.owners={};self.objects={};self.leases={};self.calls=[];self.deleted=[];self.lock=RLock()
        self.on_assert=None
        self.on_storage_read=None
        self.storage_reads=[]
        self.auth_profiles={token:{"id":owner,"is_anonymous":True} for token,owner in OWNERS.items()}
        self.analysis_revisions={}
        self.client=httpx.Client(transport=httpx.MockTransport(self.handle))
        self.repository=SupabaseCaptureRepository(self.settings,self.client)

    def owned(self,owner,cid,revision=None):
        row=self.rows.get(cid)
        if not row or self.owners[cid]!=owner or row["state"]=="deleting" or datetime.fromisoformat(row["expiresAt"])<=datetime.now(timezone.utc):
            raise CaptureError("not-found","Unavailable",404)
        if revision is not None and row["revision"]!=revision: raise CaptureError("stale-capture","Changed")
        return row

    def revoke(self,row):
        row.update(revision=row["revision"]+1,state="draft",confirmedRevision=None,roomHash=None,room=None)

    def user(self,owner,action,cid,revision,payload):
        if action=="create":
            if payload.get("consent") is not True: raise CaptureError("not-found","Unavailable",404)
            now=datetime.now(timezone.utc);cid=str(uuid4())
            row={"id":cid,"revision":1,"state":"draft","createdAt":now.isoformat(),"expiresAt":(now+timedelta(hours=24)).isoformat(),
                 "draft":CaptureDraft().model_dump(mode="json"),"photos":[],"confirmedRevision":None,"roomHash":None,"room":None,"cleanupStatus":"none","calibrations":[]}
            self.rows[cid]=row;self.owners[cid]=owner
            return row
        if action=="delete-status":
            row=self.rows.get(cid)
            if self.owners.get(cid)!=owner or not row or row["state"]!="deleting": raise CaptureError("not-found","Unavailable",404)
            return {"id":cid,"state":"deleting","inaccessible":True,"cleanupStatus":row["cleanupStatus"]}
        row=self.owned(owner,cid,revision if action not in ("read","release") else None)
        if action=="read": return row
        if action=="lease":
            active=[item for item in self.leases.values() if item[0]==owner and item[3]>datetime.now(timezone.utc)]
            kind=payload["kind"]
            if len(active)>=2 or kind in ("upload","vision") and any(item[4]==kind for item in active): raise CaptureError("busy","Busy")
            token=str(uuid4());self.leases[token]=(owner,cid,revision,datetime.now(timezone.utc)+timedelta(seconds=payload.get("seconds",120)),kind)
            return {"lease":token}
        if action=="release": self.leases.pop(payload["lease"],None);return {}
        if action=="assert":
            if self.on_assert: self.on_assert(self,row)
            item=self.leases.get(payload["lease"])
            if not item or item[:3]!=(owner,cid,revision) or item[3]<=datetime.now(timezone.utc): raise CaptureError("lease-expired","Expired")
            if payload.get("roomHash") and payload["roomHash"]!=row["roomHash"]: raise CaptureError("stale-capture","Changed")
            self.owned(owner,cid,revision);return {}
        if action=="delete":
            self.deleted.extend(self.key(owner,cid,p["id"]) for p in row["photos"])
            row.update(state="deleting",revision=row["revision"]+1,room=None,roomHash=None,confirmedRevision=None,draft=CaptureDraft().model_dump(mode="json"),photos=[],cleanupStatus="pending",calibrations=[])
            self.leases={key:value for key,value in self.leases.items() if value[1]!=cid}
            return row
        if any(value[1]==cid and value[2]==row["revision"] and value[3]>datetime.now(timezone.utc) for value in self.leases.values()): raise CaptureError("busy","Busy")
        if action=="draft": row["draft"]=payload["draft"]
        elif action=="reserve":
            if len(row["photos"])>=8 or sum(p["declaredBytes"] for p in row["photos"])+payload["declaredBytes"]>32000000: raise CaptureError("quota","Quota")
            row["photos"].append({"id":str(uuid4()),"primaryWallId":payload["primaryWallId"],"observedWallIds":[],"state":"reserved","declaredBytes":payload["declaredBytes"],
                "inputBytes":0,"canonicalBytes":0,"sha256":None,"widthPx":0,"heightPx":0,"analysisStatus":"pending","analysisAttempts":0,"semantics":None})
        elif action in ("associate","remove-photo"):
            photo=next((p for p in row["photos"] if p["id"]==payload["photoId"]),None)
            if not photo: raise CaptureError("not-found","Unavailable",404)
            if action=="associate": photo.update(primaryWallId=payload["primaryWallId"],observedWallIds=payload["observedWallIds"],semantics=None,analysisStatus="unknown")
            else: row["photos"].remove(photo);self.deleted.append(self.key(owner,cid,photo["id"]))
        else: raise CaptureError("not-found","Unknown",404)
        self.revoke(row);return row

    def authority(self,body):
        owner,cid,revision=body["p_owner"],body["p_capture"],body["p_revision"]
        if not any(p.get("id")==owner and p.get("is_anonymous") is True for p in self.auth_profiles.values()):raise CaptureError("not-found","Unavailable",404)
        row=self.owned(owner,cid,revision);payload=body["p_payload"];action=body["p_action"]
        lease=self.leases.get(body["p_lease"])
        if not lease or lease[:3]!=(owner,cid,revision) or lease[3]<=datetime.now(timezone.utc): raise CaptureError("lease-expired","Expired")
        if action in ("finalize-photo","begin-analysis","semantics","upload-failed","analysis-failed"):
            photo=next(p for p in row["photos"] if p["id"]==payload["photoId"])
        if action=="finalize-photo":
            if any(p["sha256"]==payload["sha256"] for p in row["photos"] if p is not photo): raise CaptureError("quota","Duplicate")
            if payload["inputBytes"]>photo["declaredBytes"] or photo["state"]!="reserved": raise CaptureError("quota","Quota")
            photo.update(state="accepted",**{key:payload[key] for key in ("inputBytes","canonicalBytes","sha256","widthPx","heightPx")})
        elif action=="upload-failed": photo["state"]="failed";self.deleted.append(self.key(owner,cid,photo["id"]))
        elif action=="begin-analysis":
            if photo["analysisAttempts"]>=2: raise CaptureError("attempt-limit","Limit")
            photo["analysisAttempts"]+=1;photo["analysisStatus"]="pending";self.analysis_revisions[photo["id"]]=revision
        elif action=="analysis-failed": photo["analysisStatus"]="failed"
        elif action=="semantics":
            if photo["analysisStatus"]!="pending" or self.analysis_revisions.get(photo["id"])!=revision or photo["sha256"]!=payload["sha256"]: raise CaptureError("stale-capture","Changed")
            proposal=payload["semantics"]
            openings=(photo.get("semantics") or {}).get("openings",[])+proposal["openings"]
            valid_walls={"wall-north","wall-east","wall-south","wall-west"}
            affected={photo["primaryWallId"],*photo["observedWallIds"],*(opening["wallId"] for opening in openings if opening.get("wallId") in valid_walls)}
            if any(opening.get("wallId") is None for opening in openings):affected=valid_walls
            photo.update(semantics=proposal,analysisStatus="complete")
            row["draft"]["wallReviews"]=[wall for wall in row["draft"]["wallReviews"] if wall not in affected]
            if proposal["detectedFurniture"]!="absent":row["draft"]["furnitureAcknowledged"]=False
            self.revoke(row)
        elif action=="confirm": row.update(state="confirmed",confirmedRevision=revision,room=payload["room"],roomHash=payload["roomHash"])
        elif action=="calibration": row["calibrations"].append(payload)
        return row

    @staticmethod
    def key(owner,cid,pid): return f"{owner}/{cid}/{pid}.jpg"
    def handle(self,request):
        with self.lock:
            self.calls.append((request.method,request.url.path,request.headers.get("authorization","")))
            token=request.headers.get("authorization","").removeprefix("Bearer ")
            owner=OWNERS.get(token)
            path=request.url.path
            try:
                if path=="/auth/v1/user":
                    return httpx.Response(200,json=self.auth_profiles[token]) if owner else httpx.Response(401,json={})
                if path=="/rest/v1/rpc/capture_user_operation":
                    if not owner or self.auth_profiles[token].get("is_anonymous") is not True: return httpx.Response(403,json={"message":"not-found"})
                    b=json.loads(request.content);value=self.user(owner,b["p_action"],b["p_capture"],b["p_revision"],b["p_payload"])
                elif path=="/rest/v1/rpc/capture_authority":
                    if token!=self.settings.secret_key: return httpx.Response(403,json={})
                    value=self.authority(json.loads(request.content))
                elif path.startswith("/storage/v1/object/authenticated/captures/"):
                    return httpx.Response(404,json={"code":"NoSuchKey"})
                elif path.startswith("/storage/v1/object/captures/") and request.method=="GET":
                    if token!=self.settings.secret_key: return httpx.Response(404,json={"code":"NoSuchKey"})
                    assert request.headers["apikey"]==self.settings.secret_key
                    assert list(request.url.params.keys())==["cacheNonce"]
                    nonce=request.url.params["cacheNonce"]
                    assert str(UUID(nonce))==nonce and UUID(nonce).version==4
                    assert nonce not in [r.url.params["cacheNonce"] for r in self.storage_reads]
                    self.storage_reads.append(request)
                    key=path.split("/captures/",1)[1];data=self.objects[key]
                    if self.on_storage_read:self.on_storage_read(self)
                    # Service bypass alone intentionally does not check Capture state.
                    return httpx.Response(200,content=data,headers={"X-Storage-Internal":"not-for-clients"})
                elif path.startswith("/storage/v1/object/captures/") and request.method=="POST":
                    if token!=self.settings.secret_key: return httpx.Response(403,json={})
                    key=path.split("/captures/",1)[1]
                    if key in self.objects: return httpx.Response(409,json={"message":"quota"})
                    self.objects[key]=request.content;value={}
                else: return httpx.Response(404,json={})
                return httpx.Response(200,json=deepcopy(value))
            except CaptureError as error: return httpx.Response(error.status_code,json={"message":error.code})
            except KeyError: return httpx.Response(404,json={"message":"not-found"})
