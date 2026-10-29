"""Opt-in REAL development proof using disposable anonymous owners/synthetic photos.

No provider calls. No credentials/response bodies in reports. Not authorized in
the builder turn. Fault/restart/expiry/rotation additionally follows docs/capture.md.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4
import httpx
from PIL import Image


def _json(message):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError("duplicate JSON field")
            result[key]=value
        return result
    try:
        return json.loads(message.content,object_pairs_hook=pairs) if len(message.content)<=65536 else None
    except (ValueError, UnicodeError):
        return None


def _canonical_key(key: str) -> bool:
    if not isinstance(key,str):return False
    parts=key.removesuffix(".jpg").split("/")
    try:
        return key.endswith(".jpg") and len(parts)==3 and all(str(UUID(part))==part for part in parts)
    except (ValueError, AttributeError):
        return False


def _request(response):
    try:return response.request
    except RuntimeError:return None


def _body_status(body, status: int) -> bool:
    return type(body.get("statusCode")) in (str,int) and body["statusCode"] in (status,str(status))


@dataclass(frozen=True,repr=False)
class Caller:
    # These are the two successfully created anonymous fixtures, public-only, or
    # trusted verification transport. Never serialize credentials in evidence.
    kind: str
    api_key: str
    token: str|None=None
    api_key_verified: bool=False


@dataclass(frozen=True,repr=False)
class ExpectedRequest:
    method: str
    url: str
    caller: Caller
    payload: dict|None=None
    content: bytes|None=None
    media: str|None=None


def _caller_valid(caller: Caller, *, trusted=False) -> bool:
    if not isinstance(caller,Caller) or not isinstance(caller.api_key,str) or not caller.api_key:return False
    if trusted:return caller.kind=="service" and caller.token==caller.api_key
    if caller.kind=="publishable":return caller.token is None
    return caller.kind in ("A","B") and isinstance(caller.token,str) and bool(caller.token) and caller.token!=caller.api_key


def _matches(response: httpx.Response, expected: ExpectedRequest, *, allow_loopback=False) -> bool:
    """Compare to independent intended context, never infer it from an error."""
    request=_request(response)
    target=httpx.URL(expected.url)
    scheme_valid=target.scheme=="https" or allow_loopback and target.scheme=="http" and target.host in ("127.0.0.1","::1","localhost")
    if request is None or not scheme_valid or target.userinfo or target.fragment:return False
    if request.method!=expected.method or request.url!=target:return False
    if request.headers.get_list("apikey")!=[expected.caller.api_key]:return False
    authorization=[] if expected.caller.token is None else ["Bearer "+expected.caller.token]
    if request.headers.get_list("authorization")!=authorization:return False
    if expected.content is not None:
        return expected.payload is None and request.content==expected.content and request.headers.get("content-type")==expected.media
    if expected.payload is None:return request.content==b""
    # JSON type distinctions matter (true is not a numeric revision or limit).
    return request.headers.get("content-type")=="application/json" and json.dumps(_json(request),sort_keys=True)==json.dumps(expected.payload,sort_keys=True)


def _self_content_location(response: httpx.Response, expected: ExpectedRequest|None) -> bool:
    """PostgREST table self-reference, never a redirect or a Storage exception."""
    values=response.headers.get_list("content-location")
    if len(values)!=1 or expected is None:return False
    if not _valid_data_request(expected,listing=True) or not _matches(response,expected):return False
    location=values[0]
    # Reject before parsing: urlsplit otherwise normalizes some controls. Only
    # decode the query once; the table path must be the literal expected table.
    if not location or any(ord(c)<=32 or ord(c)>=127 or c in "\\,#" for c in location):return False
    if re.search(r"%(?![0-9a-fA-F]{2})",location):return False
    try:
        reference=urlsplit(location)
        target=httpx.URL(expected.url)
        if reference.scheme or reference.netloc or reference.fragment or reference.path!="/"+target.path.rsplit("/",1)[1]:return False
        pairs=parse_qsl(reference.query,keep_blank_values=True,strict_parsing=True,encoding="utf-8",errors="strict")
    except ValueError:return False
    return len(pairs)==len({key for key,_ in pairs}) and sorted(pairs)==sorted(target.params.multi_items())


def _safe_json(response: httpx.Response, *, read_expected: ExpectedRequest|None=None):
    # Unknown response fields fail closed below; binary/signing artifacts must
    # never bypass the envelope checks through a generic permission branch.
    if response.headers.get("content-type","").split(";",1)[0]!="application/json":return None
    if any(header in response.headers for header in ("location","authorization","x-token","x-signed-url")):return None
    if "content-location" in response.headers and not _self_content_location(response,read_expected):return None
    return _json(response)


def _error(response: httpx.Response, fields: set[str], *, read_expected: ExpectedRequest|None=None):
    body=_safe_json(response,read_expected=read_expected)
    if not isinstance(body,dict) or not set(body)<=fields|{"message","details","hint"}:return None
    for field in ("message","details","hint"):
        value=body.get(field)
        if value is not None and (not isinstance(value,str) or any(text in value.lower() for text in ("https:","http:","data:","signedurl","token","/9j/"))):return None
    return body


def _uuid(value) -> bool:
    try:return isinstance(value,str) and str(UUID(value))==value
    except ValueError:return False


def _positive_integer(value) -> bool:
    return type(value) is int and value>0


def capture_get_pair_denied(foreign: httpx.Response, absent: httpx.Response,
                           foreign_expected: ExpectedRequest, absent_expected: ExpectedRequest,
                           capture_id: str, missing_id: str) -> bool:
    """Exact auth-first FastAPI contract, separate from Data API/Storage proof."""
    if not _uuid(capture_id) or not _uuid(missing_id) or capture_id==missing_id:return False
    if not isinstance(foreign_expected,ExpectedRequest) or not isinstance(absent_expected,ExpectedRequest):return False
    caller=foreign_expected.caller
    if caller!=absent_expected.caller or not _caller_valid(caller) or caller.kind not in ("B","publishable"):return False
    if caller.kind=="publishable" and caller.api_key_verified is not True:return False
    origins=[]
    for response,expected,identity in ((foreign,foreign_expected,capture_id),(absent,absent_expected,missing_id)):
        target=httpx.URL(expected.url)
        if expected.method!="GET" or target.path!="/api/captures/"+identity or target.query or expected.payload is not None or expected.content is not None:return False
        if not _matches(response,expected,allow_loopback=True):return False
        origins.append((target.scheme,target.host,target.port))
    if origins[0]!=origins[1]:return False
    status,body=(404,{"detail":{"code":"not-found","detail":"This Capture is unavailable."}}) if caller.kind=="B" else (
        401,{"detail":{"code":"authentication-required","detail":"Refresh or restore your account to continue."}})
    return (foreign.status_code==absent.status_code==status and _safe_json(foreign)==body and
        _safe_json(absent)==body and foreign.content==absent.content)


def _valid_data_request(expected: ExpectedRequest, *, listing=False) -> bool:
    if not isinstance(expected,ExpectedRequest):return False
    if not _caller_valid(expected.caller):return False
    target=httpx.URL(expected.url);path=target.path;data=expected.payload
    if expected.content is not None:return False
    if path in ("/rest/v1/captures","/rest/v1/capture_photos"):
        table=path.rsplit("/",1)[1]
        if listing:
            return (expected.method=="GET" and expected.caller.kind in ("B","publishable") and data is None and
                set(target.params)=={"select","owner_id"} and len(target.params.multi_items())==2 and target.params["select"]=="*" and
                target.params["owner_id"].startswith("eq.") and _uuid(target.params["owner_id"][3:]))
        if expected.method=="POST" and not target.query and isinstance(data,dict):
            if table=="captures":return set(data)=={"id","owner_id","draft"} and _uuid(data["id"]) and _uuid(data["owner_id"]) and isinstance(data["draft"],dict) and bool(data["draft"])
            return (set(data)=={"id","owner_id","capture_id","object_key","primary_wall_id","declared_bytes"} and
                all(_uuid(data[field]) for field in ("id","owner_id","capture_id")) and
                data["object_key"]==f"{data['owner_id']}/{data['capture_id']}/{data['id']}.jpg" and
                data["primary_wall_id"] in ("wall-north","wall-east","wall-south","wall-west") and _positive_integer(data["declared_bytes"]))
        if set(target.params)!={"id"} or len(target.params.multi_items())!=1 or not target.params["id"].startswith("eq.") or not _uuid(target.params["id"][3:]):return False
        if expected.method=="DELETE":return data is None
        if expected.method!="PATCH" or not isinstance(data,dict):return False
        if table=="capture_photos" and set(data)=={"owner_id","capture_id","object_key"}:
            return _uuid(data["owner_id"]) and _uuid(data["capture_id"]) and data["object_key"]==f"{data['owner_id']}/{data['capture_id']}/{target.params['id'][3:]}.jpg"
        if len(data)!=1:return False
        field,value=next(iter(data.items()))
        if table=="captures":
            if field in ("draft","validated_room"):return isinstance(value,dict) and bool(value)
            if field in ("revision","confirmed_revision"):return _positive_integer(value)
            if field=="room_hash":return isinstance(value,str) and len(value)==64 and all(c in "0123456789abcdef" for c in value)
            if field=="calibrations":return value==[]
            return field=="policy_version" and isinstance(value,str) and bool(value)
        if field=="primary_wall_id":return value in ("wall-north","wall-east","wall-south","wall-west")
        if field=="state":return value=="failed"
        if field=="sha256":return isinstance(value,str) and len(value)==64 and all(c in "0123456789abcdef" for c in value)
        if field=="analysis_attempts":return type(value) is int and 0<=value<=2
        return field=="semantics" and isinstance(value,dict) and set(value)=={"openings","detectedFurniture","observation"} and value["openings"]==[] and value["detectedFurniture"]=="absent" and isinstance(value["observation"],str)
    if listing or expected.method!="POST" or target.query or not isinstance(data,dict):return False
    if path=="/rest/v1/rpc/capture_cleanup":return data=={"p_action":"claim","p_payload":{}}
    if path!="/rest/v1/rpc/capture_authority" or set(data)!={"p_action","p_owner","p_capture","p_revision","p_lease","p_payload"}:return False
    payload=data["p_payload"]
    return (data["p_action"]=="confirm" and all(_uuid(data[field]) for field in ("p_owner","p_capture","p_lease")) and _positive_integer(data["p_revision"]) and
        isinstance(payload,dict) and set(payload)=={"room","roomHash"} and isinstance(payload["room"],dict) and bool(payload["room"]) and
        isinstance(payload["roomHash"],str) and len(payload["roomHash"])==64 and all(c in "0123456789abcdef" for c in payload["roomHash"]))


def data_api_denied(response: httpx.Response, expected: ExpectedRequest, *, listing=False) -> bool:
    if not _valid_data_request(expected,listing=listing) or not _matches(response,expected):return False
    body=_error(response,{"code"},read_expected=expected if listing else None)
    # PostgREST maps insufficient privileges to401 for its unauthenticated role.
    # This exception never establishes an authenticated A/B policy rejection.
    status_valid=response.status_code==403 or (response.status_code==401 and expected.caller.kind=="publishable" and expected.caller.api_key_verified is True)
    return status_valid and body is not None and body.get("code")=="42501"


def data_api_list_denied(response: httpx.Response, expected: ExpectedRequest) -> bool:
    return _valid_data_request(expected,listing=True) and _matches(response,expected) and (
        response.status_code==200 and _safe_json(response,read_expected=expected)==[] or data_api_denied(response,expected,listing=True))


def _storage_context(expected: ExpectedRequest, operation: str, key: str, *, trusted=False) -> bool:
    if not isinstance(expected,ExpectedRequest):return False
    if not _canonical_key(key) or not _caller_valid(expected.caller,trusted=trusted):return False
    target=httpx.URL(expected.url)
    if trusted and operation=="read":
        pairs=target.params.multi_items()
        if len(pairs)!=1 or pairs[0][0]!="cacheNonce" or not _uuid(pairs[0][1]) or UUID(pairs[0][1]).version!=4:return False
    elif target.query:return False
    if operation=="list":
        return expected.method=="POST" and target.path=="/storage/v1/object/list/captures" and expected.content is None and json.dumps(expected.payload,sort_keys=True)==json.dumps({"prefix":key.rsplit("/",1)[0],"limit":100},sort_keys=True)
    if operation=="delete":
        return expected.method=="DELETE" and target.path=="/storage/v1/object/captures" and expected.content is None and expected.payload=={"prefixes":[key]}
    if operation=="sign":
        return expected.method=="POST" and target.path=="/storage/v1/object/sign/captures/"+key and expected.content is None and isinstance(expected.payload,dict) and type(expected.payload.get("expiresIn")) is int and expected.payload=={"expiresIn":60}
    if operation in ("read","read-ordinary"):
        if trusted and operation!="read":return False
        path="/storage/v1/object/"+("" if trusted or operation=="read-ordinary" else "authenticated/")+"captures/"+key
        return expected.method=="GET" and target.path==path and expected.payload is None and expected.content is None
    if operation not in ("upload","overwrite"):return False
    return expected.method==("POST" if operation=="upload" else "PUT") and target.path=="/storage/v1/object/captures/"+key and expected.payload is None and isinstance(expected.content,bytes) and 0<len(expected.content)<=400000 and expected.media=="image/jpeg"


def storage_write_denied(response: httpx.Response, expected: ExpectedRequest, operation: str, key: str) -> bool:
    if operation not in ("upload","overwrite","delete") or not _storage_context(expected,operation,key) or not _matches(response,expected):return False
    body=_error(response,{"code","error","statusCode"})
    return response.status_code==400 and body is not None and body.get("code")=="AccessDenied" and body.get("error")=="Unauthorized" and _body_status(body,403)


def storage_object_unavailable(response: httpx.Response, expected: ExpectedRequest, key: str, *, signing=False, trusted=False, ordinary=False) -> bool:
    """Known-key hidden/missing envelope, never standalone physical absence."""
    if signing and (trusted or ordinary) or trusted and ordinary:return False
    if not _storage_context(expected,"sign" if signing else "read-ordinary" if ordinary else "read",key,trusted=trusted) or not _matches(response,expected):return False
    body=_error(response,{"code","error","statusCode"})
    return response.status_code in (400,404) and body is not None and body.get("code")=="NoSuchKey" and body.get("error")=="not_found" and _body_status(body,404)


def storage_list_denied(response: httpx.Response, expected: ExpectedRequest, key: str) -> bool:
    return _storage_context(expected,"list",key) and _matches(response,expected) and response.status_code==200 and _safe_json(response)==[]


def _listed_object(response: httpx.Response, expected: ExpectedRequest, key: str) -> tuple[bool,str|None]:
    if not _storage_context(expected,"list",key,trusted=True) or not _matches(response,expected):return False,None
    filename=key.rsplit("/",1)[1];rows=_safe_json(response)
    if response.status_code!=200 or not isinstance(rows,list) or len(rows)>=100:return False,None
    found=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("name"),str) or "/" in row["name"] or "id" not in row:return False,None
        identity=row["id"]
        try:
            if identity is not None and str(UUID(identity))!=identity:return False,None
        except (ValueError,TypeError,AttributeError):return False,None
        if row["name"]==filename:
            if identity is None:return False,None
            found.append(identity)
    return (True,found[0] if found else None) if len(found)<=1 else (False,None)


def storage_bytes_unchanged(read: httpx.Response, listing: httpx.Response, read_expected: ExpectedRequest, list_expected: ExpectedRequest, key: str, digest: str, object_id: str) -> bool:
    valid,identity=_listed_object(listing,list_expected,key)
    return bool(_storage_context(read_expected,"read",key,trusted=True) and _matches(read,read_expected) and
        read.status_code==200 and sha256(read.content).hexdigest()==digest and valid and identity is not None and identity==object_id)


def storage_delete_denied_or_noop(response: httpx.Response, expected: ExpectedRequest, read: httpx.Response, listing: httpx.Response, read_expected: ExpectedRequest, list_expected: ExpectedRequest, key: str, digest: str, object_id: str) -> bool:
    valid=_storage_context(expected,"delete",key) and _matches(response,expected)
    # A 200 [] is a no-op only after immediate trusted byte AND exact object checks.
    return bool(valid and (storage_write_denied(response,expected,"delete",key) or response.status_code==200 and _safe_json(response)==[]) and
        storage_bytes_unchanged(read,listing,read_expected,list_expected,key,digest,object_id))


def storage_physically_absent(read: httpx.Response, listing: httpx.Response, read_expected: ExpectedRequest, list_expected: ExpectedRequest, key: str) -> bool:
    valid,identity=_listed_object(listing,list_expected,key)
    return storage_object_unavailable(read,read_expected,key,trusted=True) and valid and identity is None


def owner_api_photo(response: httpx.Response, expected: ExpectedRequest, capture_id: str, photo_id: str, *, digest: str|None=None, deleted=False) -> bool:
    """A real signed-owner API response; service Storage success is never this proof."""
    target=httpx.URL(expected.url)
    if (not _uuid(capture_id) or not _uuid(photo_id) or not _caller_valid(expected.caller) or expected.caller.kind!="A"
            or expected.method!="GET" or target.path!=f"/api/captures/{capture_id}/photos/{photo_id}/content"
            or target.query or expected.payload is not None or expected.content is not None
            or not _matches(response,expected,allow_loopback=True)):return False
    if deleted:
        return response.status_code==404 and _safe_json(response)=={"detail":{"code":"not-found","detail":"This Capture is unavailable."}}
    return (response.status_code==200 and response.headers.get("content-type")=="image/jpeg"
        and response.headers.get("cache-control")=="no-store" and response.headers.get("x-content-type-options")=="nosniff"
        and not any(header in response.headers for header in ("location","content-location","authorization","x-token","x-signed-url"))
        and isinstance(digest,str) and len(digest)==64 and 0<len(response.content)<=400000 and sha256(response.content).hexdigest()==digest)


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--authorized-live",action="store_true");p.add_argument("--api-url",required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--wait-seconds",type=int,default=1200)
    a=p.parse_args()
    if not a.authorized_live:p.error("Explicit real development/private-write authorization is required.")
    if not 0<=a.wait_seconds<=1800:p.error("wait-seconds must be 0..1800")
    if a.output.resolve().is_relative_to(Path(__file__).resolve().parent.parent):p.error("External report required.")
    url=os.environ.get("SUPABASE_URL","").rstrip("/")
    public=os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY","")
    secret=os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
    if not url.startswith("https://") or not public or not secret or public==secret:p.error("Standard secure Supabase environment required.")
    api=a.api_url.rstrip("/");owners=[];owned_objects=set()
    report={"status":"RUNNING","kind":"REAL_DEVELOPMENT_SYNTHETIC_PRIVATE_PROOF","checks":[],
        "startedAt":datetime.now(timezone.utc).isoformat(),"paidProvider":"UNRUN","ownerPhotos":"UNRUN",
        "phone":"UNRUN","scheduledRunInspection":"UNRUN","expiryFailureRestartRotation":"UNRUN"}
    client=httpx.Client(timeout=10,follow_redirects=False,trust_env=False)
    def call(target,method,path,token=None,*,data=None,content=None,media=None,admin=False):
        headers={"apikey":secret if admin else public,"Prefer":"return=representation"}
        if token:headers["Authorization"]="Bearer "+token
        if media:headers["Content-Type"]=media
        return client.request(method,target+path,headers=headers,json=data,content=content)
    def check(name,passed):
        report["checks"].append({"name":name,"passed":bool(passed)})
        if not passed:raise RuntimeError("proof failure")
    service=Caller("service",secret,secret)
    def intended(method,path,caller,*,data=None,content=None,media=None):
        return ExpectedRequest(method,url+path,caller,data,content,media)
    def send(expected):
        return call("",expected.method,expected.url,expected.caller.token,data=expected.payload,content=expected.content,media=expected.media,admin=expected.caller.kind=="service")
    def write_denied(name,method,path,caller,data):
        expected=intended(method,path,caller,data=data)
        check(name,data_api_denied(send(expected),expected))
    def inspect_object(key):
        read=intended("GET","/storage/v1/object/captures/"+key+"?cacheNonce="+str(uuid4()),service)
        listing=intended("POST","/storage/v1/object/list/captures",service,data={"prefix":key.rsplit("/",1)[0],"limit":100})
        return send(read),send(listing),read,listing
    def create(token):
        response=call(api,"POST","/api/captures",token,data={"consent":True})
        check("consented owned creation",response.status_code==200);return response.json()
    try:
        for _ in range(2):
            response=call(url,"POST","/auth/v1/signup",data={"data":{}})
            check("real anonymous Auth",response.status_code==200);s=response.json()
            check("current anonymous fixture identity",s["user"].get("is_anonymous") is True and _uuid(s["user"]["id"]) and isinstance(s["access_token"],str) and bool(s["access_token"]))
            owners.append((s["user"]["id"],s["access_token"]))
        oa,ta=owners[0];ob,tb=owners[1];capture=create(ta);other=create(tb);cid=capture["id"]
        check("distinct valid-role callers",oa!=ob and ta!=tb and ta not in (public,secret) and tb not in (public,secret))
        # The identical configured public key has just succeeded at both real
        # anonymous Auth signups and both positive owned Capture creations.
        callers=(Caller("A",public,ta),Caller("B",public,tb),Caller("publishable",public,api_key_verified=True))
        for index,wall in enumerate(("wall-north","wall-east","wall-south","wall-west")):
            out=BytesIO();Image.new("RGB",(640,480),(40+index*20,100,180)).save(out,"PNG");image=out.getvalue()
            response=call(api,"POST",f"/api/captures/{cid}/photos",ta,data={"expectedRevision":capture["revision"],"declaredBytes":len(image),"primaryWallId":wall})
            check("reserve",response.status_code==200);capture=response.json();photo=capture["photos"][-1]
            key=f"{oa}/{cid}/{photo['id']}.jpg";owned_objects.add(key)
            response=call(api,"POST",f"/api/captures/{cid}/photos/{photo['id']}/content?expectedRevision={capture['revision']}",ta,content=image,media="image/png")
            check("canonical ingestion",response.status_code==200);capture=response.json()
        draft={**capture["draft"],"roomType":"bedroom","topology":"rectangle","widthM":6,"depthM":4,"heightM":2.5,"dimensionsConfirmed":True,"wallReviews":["wall-north","wall-east","wall-south","wall-west"],"furnitureAcknowledged":True}
        response=call(api,"PATCH",f"/api/captures/{cid}/draft",ta,data={"expectedRevision":capture["revision"],"draft":draft})
        check("persisted correction",response.status_code==200);capture=response.json()
        response=call(api,"POST",f"/api/captures/{cid}/confirm",ta,data={"expectedRevision":capture["revision"]})
        check("confirmed immutable Room",response.status_code==200 and response.json()["status"]=="confirmed");capture=response.json()["capture"]
        photo=capture["photos"][0];pid=photo["id"];key=f"{oa}/{cid}/{pid}.jpg"
        byte_path="/storage/v1/object/authenticated/captures/"+key
        def direct_reads_denied(phase):
            for caller in callers:
                for ordinary in (False,True):
                    path="/storage/v1/object/"+("" if ordinary else "authenticated/")+"captures/"+key
                    expected=intended("GET",path,caller)
                    check("direct Storage denial "+phase,storage_object_unavailable(send(expected),expected,key,ordinary=ordinary))
        direct_reads_denied("before API warm")
        api_photo=ExpectedRequest("GET",api+f"/api/captures/{cid}/photos/{pid}/content",callers[0])
        original=send(api_photo)
        check("owner API exact canonical photo GET",owner_api_photo(original,api_photo,cid,pid,digest=photo["sha256"]))
        byte_hash=sha256(original.content).hexdigest()
        direct_reads_denied("after API warm")
        inspected=inspect_object(key);listed,object_id=_listed_object(inspected[1],inspected[3],key)
        check("known existing exact Storage object",listed and object_id is not None and storage_bytes_unchanged(*inspected,key,byte_hash,object_id))
        missing="00000000-0000-0000-0000-000000000000"
        for caller in callers[1:]:
            foreign_expected=ExpectedRequest("GET",api+f"/api/captures/{cid}",caller)
            absent_expected=ExpectedRequest("GET",api+f"/api/captures/{missing}",caller)
            foreign=send(foreign_expected);absent=send(absent_expected)
            check("non-enumerating HTTP denial",capture_get_pair_denied(foreign,absent,foreign_expected,absent_expected,cid,missing))
            for table in ("captures","capture_photos"):
                expected=intended("GET",f"/rest/v1/{table}?select=*&owner_id=eq.{oa}",caller)
                check("direct foreign list denial",data_api_list_denied(send(expected),expected))
            expected=intended("GET",byte_path,caller)
            check("foreign byte denial",storage_object_unavailable(send(expected),expected,key))
        lease=call(url,"POST","/rest/v1/rpc/capture_user_operation",ta,data={"p_action":"lease","p_capture":cid,"p_revision":capture["revision"],"p_payload":{"kind":"confirm"}})
        check("owned protected authority lease",lease.status_code==200);lease_id=lease.json()["lease"]
        for caller in callers:
            token=caller.token
            # Valid INSERTs for each actual table, with all required photo columns.
            write_denied("valid owner-for Capture INSERT","POST","/rest/v1/captures",caller,{"id":str(uuid4()),"owner_id":oa,"draft":draft})
            newpid=str(uuid4());newkey=f"{oa}/{cid}/{newpid}.jpg";owned_objects.add(newkey)
            valid_photo={"id":newpid,"owner_id":oa,"capture_id":cid,"object_key":newkey,"primary_wall_id":"wall-north","declared_bytes":1000}
            write_denied("valid owner-for photo INSERT","POST","/rest/v1/capture_photos",caller,valid_photo)
            for patch in ({"draft":{**draft,"widthM":7}}, {"confirmed_revision":capture["revision"]+1},
                          {"validated_room":{**capture["room"],"ceilingHeightM":3}}, {"room_hash":"0"*64},
                          {"calibrations":[]}, {"policy_version":"forged"}, {"revision":capture["revision"]+1}):
                write_denied("same-owner protected Capture PATCH","PATCH",f"/rest/v1/captures?id=eq.{cid}",caller,patch)
            for patch in ({"primary_wall_id":"wall-east"},{"state":"failed"},{"sha256":"0"*64},
                          {"analysis_attempts":1},{"semantics":{"openings":[],"detectedFurniture":"absent","observation":"clear"}}):
                write_denied("same-owner protected photo PATCH","PATCH",f"/rest/v1/capture_photos?id=eq.{pid}",caller,patch)
            # B Capture exists; both composite FK and canonical path are valid.
            reparented_key=f"{ob}/{other['id']}/{pid}.jpg";owned_objects.add(reparented_key)
            write_denied("valid cross-owner photo reparent","PATCH",f"/rest/v1/capture_photos?id=eq.{pid}",caller,
                {"owner_id":ob,"capture_id":other["id"],"object_key":reparented_key})
            for table,rowid in (("captures",cid),("capture_photos",pid)):
                write_denied("direct metadata DELETE","DELETE",f"/rest/v1/{table}?id=eq.{rowid}",caller,None)
            for method,path,payload,blob in [
                ("POST","/storage/v1/object/captures/"+newkey,None,original.content),
                ("PUT","/storage/v1/object/captures/"+key,None,original.content),
                ("POST","/rest/v1/rpc/capture_authority",{"p_action":"confirm","p_owner":oa,"p_capture":cid,"p_revision":capture["revision"],"p_lease":lease_id,"p_payload":{"room":capture["room"],"roomHash":capture["roomHash"]}},None),
                ("POST","/rest/v1/rpc/capture_cleanup",{"p_action":"claim","p_payload":{}},None),
            ]:
                if blob is None:write_denied("direct protected RPC write",method,path,caller,payload)
                else:
                    expected=intended(method,path,caller,content=blob,media="image/jpeg")
                    check("direct protected Storage write",storage_write_denied(send(expected),expected,"upload" if method=="POST" else "overwrite",newkey if method=="POST" else key))
            expected=intended("DELETE","/storage/v1/object/captures",caller,data={"prefixes":[key]})
            deletion=send(expected);inspected=inspect_object(key)
            check("Storage DELETE denied or verified unchanged no-op",storage_delete_denied_or_noop(deletion,expected,*inspected,key,byte_hash,object_id))
            expected=intended("POST","/storage/v1/object/sign/captures/"+key,caller,data={"expiresIn":60})
            signing=send(expected);inspected=inspect_object(key)
            check("existing-key sign denied with object unchanged",storage_object_unavailable(signing,expected,key,signing=True) and storage_bytes_unchanged(*inspected,key,byte_hash,object_id))
            expected=intended("POST","/storage/v1/object/list/captures",caller,data={"prefix":f"{oa}/{cid}","limit":100})
            check("private Storage LIST denial",storage_list_denied(send(expected),expected,key))
        call(url,"POST","/rest/v1/rpc/capture_user_operation",ta,data={"p_action":"release","p_capture":cid,"p_revision":capture["revision"],"p_payload":{"lease":lease_id}})
        current=call(api,"GET",f"/api/captures/{cid}",ta)
        check("A rows unchanged by attacks",current.status_code==200 and current.json()==capture)
        unchanged=send(api_photo);check("A bytes unchanged",owner_api_photo(unchanged,api_photo,cid,pid,digest=byte_hash))
        response=call(api,"DELETE",f"/api/captures/{cid}",ta,data={"expectedRevision":capture["revision"]})
        check("immediate tombstone",response.status_code==200 and response.json()["state"]=="deleting")
        check("same API photo URL revoked after delete",owner_api_photo(send(api_photo),api_photo,cid,pid,deleted=True))
        direct_reads_denied("post-delete")
        deadline=time.monotonic()+a.wait_seconds;physical=False
        while True:
            byte_absences=[storage_physically_absent(*inspect_object(k),k) for k in owned_objects if k.startswith(f"{oa}/{cid}/")]
            metadata=call(url,"GET",f"/rest/v1/captures?id=eq.{cid}&select=id",secret,admin=True)
            if metadata.status_code==200 and metadata.json()==[]:
                check("physical bytes gone before metadata purge",all(byte_absences));physical=True;break
            if time.monotonic()>=deadline:break
            time.sleep(15)
        check("physical scheduled removal without direct invocation",physical)
        report["status"]="CORE_LIVE_PASS_ADDITIONAL_GATES_UNRUN"
    except Exception as failure:report["status"]="FAIL";report["failureType"]=type(failure).__name__
    finally:
        cleanup=True
        # Admin cleanup scope is ONLY these two newly created disposable owners.
        # Expire accidentally accepted/mutated rows preserving the 24h invariant;
        # normal durable cleanup removes manifests only after physical byte removal.
        for owner,token in owners:
            try:
                rows=call(url,"GET",f"/rest/v1/captures?owner_id=eq.{owner}&select=id,revision,state",secret,admin=True)
                if rows.status_code!=200:cleanup=False;continue
                for row in rows.json():
                    deleted=call(api,"DELETE",f"/api/captures/{row['id']}",token,data={"expectedRevision":row["revision"]})
                    if deleted.status_code!=200 and row["state"]!="deleting":
                        created=datetime.now(timezone.utc).timestamp()-90000
                        expired=call(url,"PATCH",f"/rest/v1/captures?id=eq.{row['id']}&owner_id=eq.{owner}",secret,admin=True,
                            data={"created_at":datetime.fromtimestamp(created,timezone.utc).isoformat(),"expires_at":datetime.fromtimestamp(created+86400,timezone.utc).isoformat()})
                        cleanup &= expired.status_code in (200,204)
            except Exception:cleanup=False
        # A forbidden metadata DELETE/INSERT might leave unmanifested test bytes.
        # Remove only inventoried disposable keys via actual Storage API, never SQL.
        for key in owned_objects:
            try:
                call(url,"DELETE","/storage/v1/object/captures",secret,admin=True,data={"prefixes":[key]})
                cleanup &= storage_physically_absent(*inspect_object(key),key)
            except Exception:cleanup=False
        report["fixtureCleanup"]="BYTES_REMOVED_METADATA_PENDING_DURABLE_SCHEDULE" if cleanup else "ATTENTION_REQUIRED"
        client.close();report["finishedAt"]=datetime.now(timezone.utc).isoformat()
        a.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    return 0 if report["status"].startswith("CORE_LIVE_PASS") else 1


if __name__=="__main__":raise SystemExit(main())
