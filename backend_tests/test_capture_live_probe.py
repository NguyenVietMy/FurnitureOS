"""Adversarial proof boundaries; all requests and credentials are offline fixtures."""
from dataclasses import replace
from hashlib import sha256
import json
from types import SimpleNamespace
import httpx
import pytest
from scripts import ticket9_supabase_evidence as probe

OWNER="11111111-1111-1111-1111-111111111111"
CAPTURE="33333333-3333-3333-3333-333333333333"
PHOTO="44444444-4444-4444-4444-444444444444"
KEY=f"{OWNER}/{CAPTURE}/{PHOTO}.jpg"
OBJECT="55555555-5555-5555-5555-555555555555"
BYTES=b"exact disposable canonical JPEG"
DIGEST=sha256(BYTES).hexdigest()
MISSING={"code":"NoSuchKey","error":"not_found","statusCode":"404"}
DENIED={"code":"AccessDenied","error":"Unauthorized","statusCode":"403"}
A=probe.Caller("A","fake-public","fake-token-A")
B=probe.Caller("B","fake-public","fake-token-B")
PUBLIC=probe.Caller("publishable","fake-public",api_key_verified=True)
SERVICE=probe.Caller("service","fake-service","fake-service")
DRAFT={"roomType":"bedroom","topology":"rectangle","widthM":6,"depthM":4,"heightM":2.5}
MISSING_CAPTURE="00000000-0000-0000-0000-000000000000"
API_NOT_FOUND={"detail":{"code":"not-found","detail":"This Capture is unavailable."}}
API_AUTH_REQUIRED={"detail":{"code":"authentication-required","detail":"Restore your anonymous account to continue."}}


def expected(kind,caller=A):
    specs={
        "data":("PATCH",f"/rest/v1/captures?id=eq.{CAPTURE}",{"revision":2},None,None),
        "rpc":("POST","/rest/v1/rpc/capture_cleanup",{"p_action":"claim","p_payload":{}},None,None),
        "data-list":("GET",f"/rest/v1/capture_photos?select=*&owner_id=eq.{OWNER}",None,None,None),
        "upload":("POST","/storage/v1/object/captures/"+KEY,None,BYTES,"image/jpeg"),
        "overwrite":("PUT","/storage/v1/object/captures/"+KEY,None,BYTES,"image/jpeg"),
        "delete":("DELETE","/storage/v1/object/captures",{"prefixes":[KEY]},None,None),
        "sign":("POST","/storage/v1/object/sign/captures/"+KEY,{"expiresIn":60},None,None),
        "read":("GET","/storage/v1/object/authenticated/captures/"+KEY,None,None,None),
        "list":("POST","/storage/v1/object/list/captures",{"prefix":f"{OWNER}/{CAPTURE}","limit":100},None,None),
        "trusted-read":("GET","/storage/v1/object/captures/"+KEY+"?cacheNonce=12345678-1234-4321-8123-123456789abc",None,None,None),
    }
    method,path,payload,content,media=specs[kind]
    return probe.ExpectedRequest(method,"https://local.invalid"+path,caller,payload,content,media)


def response(context,status=400,body=None,*,actual=None,content=None,headers=None):
    actual=context if actual is None else actual
    request_headers={"apikey":actual.caller.api_key}
    if actual.caller.token is not None:request_headers["Authorization"]="Bearer "+actual.caller.token
    if actual.media:request_headers["Content-Type"]=actual.media
    request=httpx.Request(actual.method,actual.url,headers=request_headers,json=actual.payload,content=actual.content)
    return httpx.Response(status,request=request,headers=headers,**({"content":content} if content is not None else {"json":body}))


def api_pair_expected(caller=B,origin="https://api.invalid",capture_id=CAPTURE):
    return (probe.ExpectedRequest("GET",origin+"/api/captures/"+capture_id,caller),
            probe.ExpectedRequest("GET",origin+"/api/captures/"+MISSING_CAPTURE,caller))


@pytest.mark.parametrize("caller,status,body",[(B,404,API_NOT_FOUND),(PUBLIC,401,API_AUTH_REQUIRED)])
@pytest.mark.parametrize("origin",["https://api.invalid","http://127.0.0.1:58123","http://[::1]:58123"])
def test_fastapi_pair_requires_known_role_envelope_and_preserves_actual_response(caller,status,body,origin):
    first,second=api_pair_expected(caller,origin)
    foreign,absent=response(first,status,body),response(second,status,body)
    original=[(item.status_code,list(item.headers.multi_items()),item.content) for item in (foreign,absent)]
    assert probe.capture_get_pair_denied(foreign,absent,first,second,CAPTURE,MISSING_CAPTURE)
    assert [(item.status_code,list(item.headers.multi_items()),item.content) for item in (foreign,absent)]==original


@pytest.mark.parametrize("caller,status,body",[(B,404,API_NOT_FOUND),(PUBLIC,401,API_AUTH_REQUIRED)])
@pytest.mark.parametrize("fault",["method","path","query","origin","apikey","bearer","payload","contextless"])
def test_fastapi_pair_rejects_wrong_actual_request_even_when_error_body_matches(caller,status,body,fault):
    first,second=api_pair_expected(caller)
    actual=first
    if fault=="method":actual=replace(first,method="POST")
    if fault=="path":actual=replace(first,url=first.url.replace(CAPTURE,OBJECT))
    if fault=="query":actual=replace(first,url=first.url+"?unexpected=true")
    if fault=="origin":actual=replace(first,url=first.url.replace("api.invalid","other.invalid"))
    if fault=="apikey":actual=replace(first,caller=replace(caller,api_key="wrong"))
    if fault=="bearer":actual=replace(first,caller=replace(caller,token="wrong"))
    if fault=="payload":actual=replace(first,payload={"unexpected":True})
    foreign=httpx.Response(status,json=body) if fault=="contextless" else response(first,status,body,actual=actual)
    assert not probe.capture_get_pair_denied(foreign,response(second,status,body),first,second,CAPTURE,MISSING_CAPTURE)


@pytest.mark.parametrize("caller,status,body",[(B,401,API_AUTH_REQUIRED),(B,403,API_NOT_FOUND),
    (PUBLIC,404,API_NOT_FOUND),(PUBLIC,403,API_AUTH_REQUIRED),(A,404,API_NOT_FOUND),
    (SERVICE,404,API_NOT_FOUND),(replace(PUBLIC,api_key_verified=False),401,API_AUTH_REQUIRED),
    (replace(PUBLIC,token="unexpected"),401,API_AUTH_REQUIRED)])
def test_fastapi_pair_does_not_swap_role_or_status_contracts(caller,status,body):
    first,second=api_pair_expected(caller)
    assert not probe.capture_get_pair_denied(response(first,status,body),response(second,status,body),first,second,CAPTURE,MISSING_CAPTURE)


@pytest.mark.parametrize("caller,status,body",[(B,404,API_NOT_FOUND),(PUBLIC,401,API_AUTH_REQUIRED)])
@pytest.mark.parametrize("fault",["code","message","extra","nested-extra","url","token","bytes","location","self-header","mismatched","non-json","different-json-bytes"])
def test_fastapi_pair_rejects_malformed_leaking_redirected_and_mismatched_bodies(caller,status,body,fault):
    first,second=api_pair_expected(caller)
    malformed=json.loads(json.dumps(body));headers=None;raw=None
    if fault=="code":malformed["detail"]["code"]="wrong-code"
    if fault=="message":malformed["detail"]["detail"]="wrong message"
    if fault=="extra":malformed["capture"]={"id":CAPTURE}
    if fault=="nested-extra":malformed["detail"]["captureId"]=CAPTURE
    if fault in ("url","token","bytes"):malformed[fault]="synthetic leak"
    if fault=="location":headers={"Location":"https://synthetic.invalid/signed"}
    if fault=="self-header":headers={"Content-Location":"/api/captures/"+CAPTURE}
    if fault=="non-json":raw=b"not json";headers={"Content-Type":"application/json"}
    if fault=="different-json-bytes":raw=json.dumps(body,indent=2).encode();headers={"Content-Type":"application/json"}
    foreign=response(first,status,malformed,headers=headers,content=raw)
    absent=response(second,status,body)
    if fault=="mismatched":absent=response(second,status,API_AUTH_REQUIRED if caller==B else API_NOT_FOUND)
    assert not probe.capture_get_pair_denied(foreign,absent,first,second,CAPTURE,MISSING_CAPTURE)


def test_fastapi_pair_requires_two_distinct_ids_same_origin_and_same_expected_caller():
    first,second=api_pair_expected()
    variants=[(first,replace(second,url=second.url.replace("api.invalid","other.invalid"))),
              (first,replace(second,caller=PUBLIC)),(first,replace(second,method="HEAD")),
              (replace(first,url="http://external.invalid/api/captures/"+CAPTURE),second)]
    for foreign_expected,absent_expected in variants:
        assert not probe.capture_get_pair_denied(response(foreign_expected,404,API_NOT_FOUND),response(absent_expected,404,API_NOT_FOUND),foreign_expected,absent_expected,CAPTURE,MISSING_CAPTURE)
    assert not probe.capture_get_pair_denied(response(first,404,API_NOT_FOUND),response(second,404,API_NOT_FOUND),first,second,CAPTURE,CAPTURE)
    assert not probe.capture_get_pair_denied(response(first,404,API_NOT_FOUND),response(second,404,API_NOT_FOUND),first,second,"not-a-uuid",MISSING_CAPTURE)
    for kind,status,body in (("data",403,{"code":"42501"}),("upload",400,DENIED)):
        context=replace(expected(kind),url=expected(kind).url.replace("https://local.invalid","http://127.0.0.1:58123"))
        assert not classify(kind,response(context,status,body),context)


def test_actual_auth_and_actual_capture_router_establish_role_pairs_without_network():
    """Actual production Auth/router/repository; only Supabase transport is controlled."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.capture_auth import SupabaseAuth,CaptureError
    from api.captures import CaptureService
    from backend_tests.capture_transport import ControlledSupabase
    service=ControlledSupabase()
    auth=SupabaseAuth(service.settings,service.client)
    before=len(service.calls)
    with pytest.raises(CaptureError) as failure:auth.verify(None)
    assert failure.value.status_code==401 and {"detail":failure.value.detail}==API_AUTH_REQUIRED
    assert len(service.calls)==before
    app=FastAPI();app.include_router(CaptureService(None,None,repository=service.repository,auth=auth).router())
    origin="http://127.0.0.1:58123"
    try:
        with TestClient(app,base_url=origin) as client:
            created=client.post("/api/captures",headers={"apikey":service.settings.public_key,"Authorization":"Bearer test-owner-a"},json={"consent":True})
            assert created.status_code==200;cid=created.json()["id"]
            for caller,status,body in ((probe.Caller("B",service.settings.public_key,"test-owner-b"),404,API_NOT_FOUND),
                                       (probe.Caller("publishable",service.settings.public_key,api_key_verified=True),401,API_AUTH_REQUIRED)):
                first,second=api_pair_expected(caller,origin,cid)
                headers={"apikey":caller.api_key}
                if caller.token is not None:headers["Authorization"]="Bearer "+caller.token
                before=len(service.calls)
                foreign,absent=client.get(first.url,headers=headers),client.get(second.url,headers=headers)
                assert foreign.status_code==absent.status_code==status
                assert foreign.json()==absent.json()==body
                assert probe.capture_get_pair_denied(foreign,absent,first,second,cid,MISSING_CAPTURE)
                if caller.kind=="publishable":assert len(service.calls)==before
    finally:service.client.close()


def inspection(*,body=BYTES,rows=None,read_actual=None,list_actual=None):
    read=expected("trusted-read",SERVICE);listing=expected("list",SERVICE)
    rows=[{"name":PHOTO+".jpg","id":OBJECT}] if rows is None else rows
    return response(read,200,content=body,actual=read_actual),response(listing,200,rows,actual=list_actual),read,listing


def classify(kind,result,context):
    if kind in ("data","rpc"):return probe.data_api_denied(result,context)
    if kind=="data-list":return probe.data_api_list_denied(result,context)
    if kind in ("upload","overwrite"):return probe.storage_write_denied(result,context,kind,KEY)
    if kind=="delete":return probe.storage_delete_denied_or_noop(result,context,*inspection(),KEY,DIGEST,OBJECT)
    if kind=="list":return probe.storage_list_denied(result,context,KEY)
    return probe.storage_object_unavailable(result,context,KEY,signing=kind=="sign")


CASES=[("data",403,{"code":"42501"}),("rpc",403,{"code":"42501"}),
    ("data-list",403,{"code":"42501"}),("data-list",200,[]),
    ("upload",400,DENIED),("overwrite",400,DENIED),("delete",400,DENIED),("delete",200,[]),
    ("sign",400,MISSING),("read",400,MISSING),("list",200,[])]


@pytest.mark.parametrize("kind,status,body",CASES)
@pytest.mark.parametrize("caller",[A,B,PUBLIC])
def test_only_exact_intended_operation_caller_and_observed_envelope_can_prove_denial(kind,status,body,caller):
    context=expected(kind,caller)
    assert classify(kind,response(context,status,body),context) is (kind!="data-list" or caller!=A)


@pytest.mark.parametrize("kind,status,body",CASES)
@pytest.mark.parametrize("fault",["missing-context","method","route","bucket","key","payload","caller","apikey","missing-bearer"])
def test_request_mismatch_cannot_be_hidden_by_permission_code_or_empty_success(kind,status,body,fault):
    context=expected(kind,B if kind=="data-list" else A)
    actual=context
    if fault=="missing-context":
        assert not classify(kind,httpx.Response(status,json=body),context);return
    if fault=="method":actual=replace(context,method="GET" if context.method!="GET" else "POST")
    if fault=="route":actual=replace(context,url="https://local.invalid/rest/v1/rpc/wrong")
    if fault=="bucket":actual=replace(context,url=context.url.replace("captures","other",1).replace("capture_photos","other"))
    if fault=="key":actual=replace(context,url=context.url.replace(CAPTURE,OBJECT).replace(OWNER,OBJECT))
    if fault=="payload":actual=replace(context,payload={"malformed":True},content=None,media=None)
    if fault=="caller":actual=replace(context,caller=replace(context.caller,token="wrong-caller"))
    if fault=="apikey":actual=replace(context,caller=replace(context.caller,api_key="wrong-key"))
    if fault=="missing-bearer":actual=replace(context,caller=PUBLIC)
    # Routes without a key/query still need a mismatched intended payload.
    if actual==context:actual=replace(context,payload={"wrong":True},content=None,media=None)
    assert not classify(kind,response(context,status,body,actual=actual),context)


@pytest.mark.parametrize("kind,status,body",CASES)
@pytest.mark.parametrize("field",["signedURL","signedUrl","url","URL","token","access_token","signature","bytes","content","data","image"])
def test_every_denial_branch_rejects_artifacts_even_when_immediate_bytes_are_unchanged(kind,status,body,field):
    context=expected(kind,B if kind=="data-list" else A)
    leaked={**body,field:"synthetic leak"} if isinstance(body,dict) else [{field:"synthetic leak"}]
    assert not classify(kind,response(context,status,leaked),context)


@pytest.mark.parametrize("kind,status,body",CASES)
def test_401_and_response_location_or_nested_artifacts_never_count_as_policy_proof(kind,status,body):
    context=expected(kind,B if kind=="data-list" else A)
    assert not classify(kind,response(context,401,{"code":"42501"}),context)
    assert not classify(kind,response(context,status,body,headers={"Location":"https://synthetic.invalid/signed"}),context)
    if isinstance(body,dict):
        for detail in ({"token":"leak"},"https://synthetic.invalid/signed","Bearer token"):
            assert not classify(kind,response(context,status,{**body,"details":detail}),context)


@pytest.mark.parametrize("status,body",[(400,{"code":"42703"}),(400,{"code":"23502"}),
    (400,{"code":"23503"}),(400,{"code":"22P02"}),(404,{"code":"PGRST202"}),
    (200,[{"id":"accepted"}]),(204,{}),(401,{"code":"42501"}),(403,{"error":"Unauthorized"}),
    (403,{"statusCode":"403"}),(403,{"code":"23503"})])
def test_data_policy_proof_requires_403_42501_not_authentication_schema_or_generic_wrappers(status,body):
    context=expected("data")
    assert not probe.data_api_denied(response(context,status,body),context)


@pytest.mark.parametrize("kind",["data","rpc","data-list"])
def test_known_401_42501_is_only_publishable_no_bearer_proof_after_positive_key_validation(kind):
    context=expected(kind,PUBLIC)
    body={"code":"42501","message":"permission denied for table captures","details":None,"hint":None}
    result=response(context,401,body)
    original=(result.status_code,list(result.headers.multi_items()),result.content)
    assert classify(kind,result,context)
    assert (result.status_code,list(result.headers.multi_items()),result.content)==original
    for caller in (A,B,replace(PUBLIC,api_key_verified=False),replace(PUBLIC,api_key_verified=1),
                   replace(PUBLIC,token="unexpected-bearer"),replace(PUBLIC,api_key=""),SERVICE):
        wrong=replace(context,caller=caller)
        assert not classify(kind,response(wrong,401,body),wrong)
    for actual in (replace(context,caller=replace(PUBLIC,api_key="wrong-key")),
                   replace(context,caller=A),replace(context,payload={"wrong":True}),
                   replace(context,url="https://wrong.invalid/rest/v1/captures")):
        assert not classify(kind,response(context,401,body,actual=actual),context)


@pytest.mark.parametrize("kind",["data","rpc","data-list"])
@pytest.mark.parametrize("body",[{"code":"PGRST301"},{"code":"PGRST302"},{"code":"bad_jwt"},
    {"code":"42703"},{"code":"23503"},{"code":"42501","token":"leak"},
    {"code":"42501","details":{"signedURL":"leak"}},{"code":"42501","message":"https://synthetic.invalid/signed"},
    {"error":"Unauthorized"},[],None])
def test_publishable_401_exception_does_not_accept_jwt_schema_constraint_or_leak_errors(kind,body):
    context=expected(kind,PUBLIC)
    assert not classify(kind,response(context,401,body),context)


@pytest.mark.parametrize("table",["captures","capture_photos"])
@pytest.mark.parametrize("caller,status,body",[(B,200,[]),(B,403,{"code":"42501"}),
    (PUBLIC,200,[]),(PUBLIC,401,{"code":"42501"})])
@pytest.mark.parametrize("query",[f"owner_id=eq.{OWNER}&select=%2A",f"select=*&owner_id=eq.{OWNER}",
    f"select=%2a&owner_id=eq.{OWNER}",f"%73elect=%2A&owner_id=eq.{OWNER}"])
def test_real_postgrest_self_content_location_accepts_only_same_decoded_query_without_mutation(table,caller,status,body,query):
    context=replace(expected("data-list",caller),url=f"https://local.invalid/rest/v1/{table}?select=*&owner_id=eq.{OWNER}")
    location=f"/{table}?{query}"
    result=response(context,status,body,headers={"Content-Location":location,"Content-Type":"application/json; charset=utf-8"})
    original=(result.status_code,list(result.headers.multi_items()),result.content)
    assert probe.data_api_list_denied(result,context)
    assert (result.status_code,list(result.headers.multi_items()),result.content)==original


BAD_SELF_REFERENCES=[
    "",f"/other?owner_id=eq.{OWNER}&select=%2A",f"/rest/v1/captures?owner_id=eq.{OWNER}&select=*",
    f"https://local.invalid/{{table}}?owner_id=eq.{OWNER}&select=*",
    f"https://user:password@local.invalid/{{table}}?owner_id=eq.{OWNER}&select=*",
    f"//local.invalid/{{table}}?owner_id=eq.{OWNER}&select=*",
    f"//user:password@external.invalid/{{table}}?owner_id=eq.{OWNER}&select=*",
    f"/{{table}}?owner_id=eq.{OWNER}&select=*#fragment",f"/{{table}}?owner_id=eq.{OWNER}&select=*#",
    f"/{{table}}?owner_id=eq.{OWNER}&select=*&token=secret",f"/{{table}}?owner_id=eq.{OWNER}&select=*&url=secret",
    f"/{{table}}?owner_id=eq.{OWNER}&select=*&signedURL=secret",f"/{{table}}?owner_id=eq.{OWNER}&select=*&bytes=secret",
    f"/{{table}}?owner_id=eq.{OWNER}&select=*&select=*",f"/{{table}}?owner_id=eq.{OWNER}&select=*&%73elect=*",
    f"/{{table}}?owner_id=eq.{OWNER}&owner_id=eq.{OWNER}&select=*",
    f"/{{table}}?owner_id=eq.{OBJECT}&select=*",f"/{{table}}?owner_id=neq.{OWNER}&select=*",
    f"/{{table}}?owner_id=eq.{OWNER}&select=id",f"/{{table}}?owner_id=eq.{OWNER}",
    f"/{{table}}?owner_id=eq.{OWNER}&select=%",f"/{{table}}?owner_id=eq.{OWNER}&select=%GG",
    f"/{{table}}?owner_id=eq.{OWNER}&select=%FF",f"/{{table}}?owner_id=eq.{OWNER}&select=%252A",
    f"/{{table}}?owner_id=eq.{OWNER}&select=*;token=secret",f"/{{table}}?owner_id=eq.{OWNER}&select=+*",
    f"/{{table}}?owner_id=eq.{OWNER}&select=*&",f"/{{table}}?owner_id=eq.{OWNER}&select=*&missingvalue",
    f"/{{table}}/../captures?owner_id=eq.{OWNER}&select=*",f"/%63aptures?owner_id=eq.{OWNER}&select=*",
    f"/{{table}}?owner_id=eq.{OWNER}&select=*\\@external.invalid",f"/{{table}}?owner_id=eq.{OWNER}&select=*\n",
    f" /{{table}}?owner_id=eq.{OWNER}&select=*",f"/{{table}}?owner_id=eq.{OWNER}&select=* ",
    f"/{{table}}?owner_id=eq.{OWNER}&select=*,/captures?owner_id=eq.{OWNER}&select=*",
]


@pytest.mark.parametrize("table",["captures","capture_photos"])
@pytest.mark.parametrize("caller,status,body",[(B,200,[]),(PUBLIC,401,{"code":"42501"})])
@pytest.mark.parametrize("location",BAD_SELF_REFERENCES)
def test_self_reference_rejects_wrong_or_ambiguous_resource_external_redirect_and_artifact_variants(table,caller,status,body,location):
    context=replace(expected("data-list",caller),url=f"https://local.invalid/rest/v1/{table}?select=*&owner_id=eq.{OWNER}")
    result=response(context,status,body,headers={"Content-Location":location.format(table=table)})
    assert not probe.data_api_list_denied(result,context)


def test_duplicate_self_header_and_contextless_or_mismatched_request_are_rejected():
    context=expected("data-list",B)
    location=f"/capture_photos?owner_id=eq.{OWNER}&select=%2A"
    duplicates=response(context,200,[],headers=[("Content-Location",location),("content-location",location)])
    assert not probe.data_api_list_denied(duplicates,context)
    assert probe._safe_json(httpx.Response(200,json=[],headers={"Content-Location":location}),read_expected=context) is None
    for actual in (replace(context,method="POST"),replace(context,caller=A),replace(context,payload={"wrong":1}),
                   replace(context,url=context.url.replace(OWNER,OBJECT))):
        assert not probe.data_api_list_denied(response(context,200,[],actual=actual,headers={"Content-Location":location}),context)
    result=response(context,200,[],headers={"Content-Location":location,"Location":"https://synthetic.invalid/signed"})
    assert not probe.data_api_list_denied(result,context)


@pytest.mark.parametrize("kind,status,body",CASES)
def test_valid_data_self_header_is_never_allowed_for_write_rpc_storage_or_without_read_context(kind,status,body):
    if kind=="data-list":return
    context=expected(kind)
    result=response(context,status,body,headers={"Content-Location":f"/capture_photos?owner_id=eq.{OWNER}&select=%2A"})
    assert not classify(kind,result,context)


@pytest.mark.parametrize("context",[
    replace(expected("data"),method="POST"),
    replace(expected("data"),url="https://local.invalid/rest/v1/other?id=eq."+CAPTURE),
    replace(expected("data"),url="https://local.invalid/rest/v1/captures?id=eq.not-a-uuid"),
    replace(expected("data"),payload={"revision":"2"}),
    replace(expected("data"),payload={"revision":True}),
    replace(expected("data"),payload={"unknown_column":2}),
    replace(expected("data"),payload={}),
    replace(expected("data"),caller=SERVICE),
    replace(expected("data"),caller=probe.Caller("unknown","fake-public","fake-token")),
    replace(expected("data"),caller=probe.Caller("A","fake-public")),
    replace(expected("data"),caller=probe.Caller("publishable","fake-public","fake-token")),
    replace(expected("rpc"),payload={"p_action":"wrong","p_payload":{}}),
    replace(expected("rpc"),url="https://local.invalid/rest/v1/rpc/capture_user_operation"),
])
def test_invalid_intended_request_cannot_be_blessed_by_matching_response_context(context):
    assert not probe.data_api_denied(response(context,403,{"code":"42501"}),context)


@pytest.mark.parametrize("kind",["upload","overwrite","delete","sign","read","list"])
def test_storage_permission_proof_cannot_use_trusted_service_or_wrong_operation(kind):
    context=expected(kind,SERVICE)
    status,body=(200,[]) if kind in ("delete","list") else (400,MISSING if kind in ("sign","read") else DENIED)
    assert not classify(kind,response(context,status,body),context)
    if kind in ("upload","overwrite"):
        valid=expected(kind)
        assert not probe.storage_write_denied(response(valid,400,DENIED),valid,"sign",KEY)


@pytest.mark.parametrize("kind,status,body",[("sign",403,{"code":"42501"}),
    ("sign",403,DENIED),("read",400,DENIED),("upload",403,{"code":"42501"}),
    ("delete",204,[]),("delete",200,[{"name":PHOTO+".jpg"}]),
    ("sign",400,{**MISSING,"code":"NoSuchBucket"}),("read",404,{}),
    ("upload",400,{**DENIED,"statusCode":403.0}),("read",400,{**MISSING,"statusCode":404.0})])
def test_storage_does_not_fall_back_to_data_codes_or_unvalidated_absence(status,body,kind):
    context=expected(kind)
    assert not classify(kind,response(context,status,body),context)


@pytest.mark.parametrize("kind",["data","sign","list","delete"])
def test_nonjson_binary_duplicate_fields_and_empty_bodies_are_not_denial(kind):
    context=expected(kind)
    for raw in (b"\xff\xd8JPEG",b"",b'{"code":"bad","code":"42501"}',b'{"code":'):
        result=response(context,403,content=raw,headers={"Content-Type":"application/json"})
        assert not classify(kind,result,context)


@pytest.mark.parametrize("status,body",[(400,DENIED),(200,[])])
def test_delete_noop_requires_immediate_original_bytes_and_same_trusted_object_id(status,body):
    context=expected("delete");result=response(context,status,body)
    assert probe.storage_delete_denied_or_noop(result,context,*inspection(),KEY,DIGEST,OBJECT)
    variants=[inspection(body=b"changed"),inspection(rows=[]),inspection(rows=[{"name":PHOTO+".jpg","id":CAPTURE}]),
        inspection(read_actual=expected("trusted-read",A)),inspection(list_actual=expected("list",A))]
    for inspected in variants:
        assert not probe.storage_delete_denied_or_noop(result,context,*inspected,KEY,DIGEST,OBJECT)


@pytest.mark.parametrize("rows",[[{}],[{"name":PHOTO+".jpg","id":None}],
    [{"name":PHOTO+".jpg","id":"bad"}],[{"name":PHOTO+".jpg","id":OBJECT}]*2,
    [{"name":"folder","id":None}]*100])
def test_malformed_duplicate_or_truncated_trusted_listing_proves_neither_presence_nor_absence(rows):
    read,listing,read_expected,list_expected=inspection(rows=rows)
    assert not probe.storage_bytes_unchanged(read,listing,read_expected,list_expected,KEY,DIGEST,OBJECT)
    missing=response(read_expected,400,MISSING)
    assert not probe.storage_physically_absent(missing,listing,read_expected,list_expected,KEY)


@pytest.mark.parametrize("status",[400,404])
def test_physical_absence_requires_exact_envelope_and_trusted_successful_empty_listing(status):
    read,listing,read_expected,list_expected=inspection(rows=[])
    missing=response(read_expected,status,MISSING)
    assert probe.storage_physically_absent(missing,listing,read_expected,list_expected,KEY)
    assert not probe.storage_physically_absent(missing,inspection()[1],read_expected,list_expected,KEY)
    for body in (DENIED,{}, {**MISSING,"code":"NoSuchBucket"},{**MISSING,"bytes":"leak"}):
        assert not probe.storage_physically_absent(response(read_expected,status,body),listing,read_expected,list_expected,KEY)
    assert not probe.storage_physically_absent(missing,response(list_expected,403,{"code":"42501"}),read_expected,list_expected,KEY)
    assert not probe.storage_physically_absent(response(read_expected,status,MISSING,actual=expected("trusted-read",A)),listing,read_expected,list_expected,KEY)


@pytest.mark.parametrize("query",["","?cacheNonce=bad","?cacheNonce=12345678-1234-1321-8123-123456789abc",
    "?cacheNonce=12345678-1234-4321-8123-123456789abc&cacheNonce=12345678-1234-4321-8123-123456789abc",
    "?cacheNonce=12345678-1234-4321-8123-123456789abc&extra=1"])
def test_trusted_absence_requires_one_canonical_uncached_uuid4(query):
    read,listing,context,list_context=inspection(rows=[])
    context=replace(context,url=context.url.split("?",1)[0]+query)
    assert not probe.storage_physically_absent(response(context,400,MISSING),listing,context,list_context,KEY)


@pytest.mark.parametrize("operation",["read","upload","overwrite","delete","sign","list"])
def test_client_or_mutation_nonce_never_relaxes_strict_storage_context(operation):
    context=expected(operation)
    context=replace(context,url=context.url+"?cacheNonce=12345678-1234-4321-8123-123456789abc")
    assert not probe._storage_context(context,operation,KEY)


def test_owner_api_proof_is_bound_to_owner_path_headers_and_canonical_hash():
    context=probe.ExpectedRequest("GET",f"https://api.invalid/api/captures/{CAPTURE}/photos/{PHOTO}/content",A)
    headers={"Content-Type":"image/jpeg","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}
    good=response(context,200,content=BYTES,headers=headers)
    assert probe.owner_api_photo(good,context,CAPTURE,PHOTO,digest=DIGEST)
    for caller in (B,PUBLIC,SERVICE):
        other=replace(context,caller=caller)
        assert not probe.owner_api_photo(response(other,200,content=BYTES,headers=headers),other,CAPTURE,PHOTO,digest=DIGEST)
    for key in ("location","content-location","x-token","x-signed-url"):
        assert not probe.owner_api_photo(response(context,200,content=BYTES,headers={**headers,key:"synthetic"}),context,CAPTURE,PHOTO,digest=DIGEST)
    for bad in (replace(context,method="POST"),replace(context,url=context.url+"?cacheNonce=123"),replace(context,url=context.url.replace(PHOTO,OBJECT))):
        assert not probe.owner_api_photo(response(bad,200,content=BYTES,headers=headers),bad,CAPTURE,PHOTO,digest=DIGEST)
    assert not probe.owner_api_photo(response(context,200,content=b"cached deleted bytes",headers=headers),context,CAPTURE,PHOTO,deleted=True)
    assert probe.owner_api_photo(response(context,404,API_NOT_FOUND),context,CAPTURE,PHOTO,deleted=True)
    assert not probe.owner_api_photo(response(context,404,{**API_NOT_FOUND,"url":"leak"}),context,CAPTURE,PHOTO,deleted=True)


@pytest.mark.parametrize("scenario",["pass","destructive-noop","data-401","sign-403-leak","sign-400-leak","list-leak","foreign-read-leak","foreign-location","public-invalid-jwt",
    "api-signed401","api-public404","api-pair-leak","api-pair-mismatch","api-redirect","final-row-changed","final-bytes-changed",
    "direct-before-leak","direct-warm-leak","direct-deleted-leak","api-deleted-cache","owner-api-missing","owner-api-wrong-hash"])
def test_live_main_offline_transport_exercises_complete_matrix_and_refuses_false_proof(monkeypatch,tmp_path,scenario):
    """Execute the real helper call sites, with no environment or network access."""
    owners=[OWNER,"22222222-2222-2222-2222-222222222222"]
    capture_ids=[CAPTURE,"66666666-6666-6666-6666-666666666666"]
    captures={};objects={};signed_in=0;deleted=set();events=[];matrix={};data_read_responses=[];data_write_statuses=set();api_pair_statuses=set();owner_byte_reads=0;direct_reads=[];nonces=set()
    def handle(request):
        nonlocal signed_in,owner_byte_reads
        path=request.url.path;method=request.method;admin=request.headers.get("authorization")=="Bearer fake-service"
        caller={"Bearer fake-token-0":"A","Bearer fake-token-1":"B",None:"publishable","Bearer fake-service":"service"}[request.headers.get("authorization")]
        assert request.headers["apikey"]==("fake-service" if admin else "fake-public")
        if not admin:
            operation=None
            if path in ("/rest/v1/captures","/rest/v1/capture_photos"):operation="data-read" if method=="GET" else "data-write"
            if path in ("/rest/v1/rpc/capture_authority","/rest/v1/rpc/capture_cleanup"):operation="rpc"
            if path=="/storage/v1/object/list/captures":operation="list"
            elif path.startswith("/storage/v1/object/sign/captures/"):operation="sign"
            elif path=="/storage/v1/object/captures" and method=="DELETE":operation="delete"
            elif path.startswith("/storage/v1/object/captures/") and method in ("POST","PUT"):operation="upload" if method=="POST" else "overwrite"
            elif method=="GET" and (path.startswith("/storage/v1/object/authenticated/captures/") or path.startswith("/storage/v1/object/captures/")):operation="bytes"
            if operation:matrix.setdefault(operation,set()).add(caller)
        data=json.loads(request.content) if request.content and request.headers.get("content-type")=="application/json" else None
        def reply(status=200,body=None,content=None,headers=None):return httpx.Response(status,headers=headers,**({"content":content} if content is not None else {"json":body}))
        if path=="/auth/v1/signup":
            index=signed_in;signed_in+=1
            return reply(body={"user":{"id":owners[index],"is_anonymous":True},"access_token":f"fake-token-{index}"})
        if path=="/api/captures":
            index=0 if request.headers.get("authorization")=="Bearer fake-token-0" else 1
            cap={"id":capture_ids[index],"revision":1,"draft":{},"photos":[],"room":{"ceilingHeightM":2.5},"roomHash":"a"*64}
            captures[cap["id"]]=cap;return reply(body=cap)
        if path.startswith("/api/captures/"):
            parts=path.split("/");cid=parts[3]
            if method=="GET" and caller=="publishable":
                status,body=(404,API_NOT_FOUND) if scenario=="api-public404" else (401,API_AUTH_REQUIRED)
                api_pair_statuses.add((caller,status));return reply(status,body)
            # Mirror production: the unauthenticated branch above does not look
            # up whether this Capture exists. Signed B reaches the owner lookup.
            cap=captures.get(cid)
            if method=="GET" and path.endswith("/content") and caller=="A":
                owner_byte_reads+=1
                if cid in deleted and scenario!="api-deleted-cache":return reply(404,API_NOT_FOUND)
                if scenario=="owner-api-missing":return reply(503,{"detail":"unavailable"})
                data=objects[f"{OWNER}/{cid}/{parts[5]}.jpg"]
                if scenario=="owner-api-wrong-hash" or scenario=="final-bytes-changed" and owner_byte_reads==2:data=b"changed"
                return reply(content=data,headers={"Content-Type":"image/jpeg","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})
            if method=="GET" and (cap is None or caller!="A"):
                status,body=(401,API_AUTH_REQUIRED) if scenario=="api-signed401" else (404,API_NOT_FOUND)
                if scenario=="api-pair-leak":body={**body,"token":"synthetic leak"}
                if scenario=="api-pair-mismatch" and cid==MISSING_CAPTURE:body=API_AUTH_REQUIRED
                api_pair_statuses.add((caller,status))
                return reply(status,body,headers={"Location":"https://synthetic.invalid/signed"} if scenario=="api-redirect" else None)
            if method=="GET":
                if scenario=="final-row-changed":cap["revision"]+=1
                return reply(body=cap)
            if method=="DELETE":deleted.add(cid);return reply(body={"state":"deleting"})
            if path.endswith("/photos"):
                pid=f"{len(cap['photos'])+10:08d}-4444-4444-4444-444444444444"
                cap["photos"].append({"id":pid});return reply(body=cap)
            if "/content" in path:
                objects[f"{OWNER}/{cid}/{parts[5]}.jpg"]=BYTES
                next(p for p in cap["photos"] if p["id"]==parts[5]).update(sha256=DIGEST,state="accepted",canonicalBytes=len(BYTES))
                return reply(body=cap)
            if path.endswith("/draft"):cap["draft"]=data["draft"];return reply(body=cap)
            if path.endswith("/confirm"):return reply(body={"status":"confirmed","capture":cap})
        if path=="/rest/v1/rpc/capture_user_operation":return reply(body={"lease":OBJECT})
        if path.startswith("/rest/v1/"):
            if method=="GET":
                if admin:return reply(body=[] if CAPTURE in deleted else [{"id":CAPTURE,"revision":1,"state":"active"}])
                table=path.rsplit("/",1)[1]
                if caller=="B":
                    location=f"/{table}?owner_id=eq.{OWNER}&select=%2A"
                    result=reply(body=[],headers={"Content-Location":"https://external.invalid/signed" if scenario=="foreign-location" else location,"Content-Type":"application/json; charset=utf-8"})
                else:
                    result=reply(401,{"code":"PGRST301" if scenario=="public-invalid-jwt" else "42501","message":"permission denied for table "+table,"details":None,"hint":None})
                data_read_responses.append((caller,table,result,result.status_code,list(result.headers.multi_items()),result.content))
                return result
            status=401 if caller=="publishable" or scenario=="data-401" else 403
            data_write_statuses.add((caller,status))
            return reply(status,{"code":"42501","message":"permission denied","details":None,"hint":None})
        if path=="/storage/v1/object/list/captures":
            events.append("trusted-list" if admin else "caller-list")
            return reply(body=[{"name":key.rsplit("/",1)[1],"id":OBJECT} for key in objects if key.startswith(data["prefix"]+"/")] if admin else [{"token":"synthetic leak"}] if scenario=="list-leak" else [])
        if path=="/storage/v1/object/captures" and method=="DELETE":
            events.append("admin-delete" if admin else "caller-delete")
            if admin or scenario=="destructive-noop":
                for key in data["prefixes"]:objects.pop(key,None)
            return reply(body=[])
        if path.startswith("/storage/v1/object/sign/"):
            if scenario=="sign-403-leak":return reply(403,{"code":"AccessDenied","signedURL":"https://synthetic.invalid/signed","token":"synthetic leak"})
            return reply(400,{**MISSING,"bytes":"synthetic leak"} if scenario=="sign-400-leak" else MISSING)
        if method in ("POST","PUT"):return reply(400,DENIED)
        key=path.removeprefix("/storage/v1/object/authenticated/captures/").removeprefix("/storage/v1/object/captures/")
        if admin:
            events.append("trusted-get")
            assert request.url.params.keys()=={"cacheNonce"} and len(request.url.params.multi_items())==1
            nonce=request.url.params["cacheNonce"]
            assert probe._uuid(nonce) and probe.UUID(nonce).version==4 and nonce not in nonces
            nonces.add(nonce)
            if CAPTURE in deleted:
                for owned in list(objects):
                    if owned.startswith(f"{OWNER}/{CAPTURE}/"):objects.pop(owned)
        if not admin:
            assert not request.url.query
            phase="post-delete" if CAPTURE in deleted else "before API warm" if owner_byte_reads==0 else "after API warm"
            direct_reads.append((phase,caller,"authenticated" if "/authenticated/" in path else "ordinary"))
            if scenario=={"before API warm":"direct-before-leak","after API warm":"direct-warm-leak","post-delete":"direct-deleted-leak"}[phase]:return reply(content=BYTES)
        if key in objects and admin:return reply(content=objects[key])
        return reply(400,{**MISSING,"url":"https://synthetic.invalid/private"} if not admin and caller in ("B","publishable") and scenario=="foreign-read-leak" else MISSING)
    original_client=httpx.Client
    monkeypatch.setattr(probe.httpx,"Client",lambda **kwargs:original_client(transport=httpx.MockTransport(handle),**kwargs))
    monkeypatch.setattr(probe,"os",SimpleNamespace(environ={"SUPABASE_URL":"https://local.invalid","SUPABASE_PUBLISHABLE_KEY":"fake-public","SUPABASE_SECRET_KEY":"fake-service"}))
    report_path=tmp_path/"offline-live-helper.json"
    monkeypatch.setattr("sys.argv",["proof","--authorized-live","--api-url","https://api.invalid","--output",str(report_path),"--wait-seconds","0"])
    assert probe.main()==(0 if scenario=="pass" else 1)
    report=json.loads(report_path.read_text(encoding="utf-8"))
    checks={row["name"]:row["passed"] for row in report["checks"]}
    failure_checks={"destructive-noop":"Storage DELETE denied or verified unchanged no-op",
        "data-401":"valid owner-for Capture INSERT","sign-403-leak":"existing-key sign denied with object unchanged",
        "sign-400-leak":"existing-key sign denied with object unchanged","list-leak":"private Storage LIST denial",
        "foreign-read-leak":"direct Storage denial before API warm","foreign-location":"direct foreign list denial","public-invalid-jwt":"direct foreign list denial",
        **{name:"non-enumerating HTTP denial" for name in ("api-signed401","api-public404","api-pair-leak","api-pair-mismatch","api-redirect")},
        "final-row-changed":"A rows unchanged by attacks","final-bytes-changed":"A bytes unchanged",
        "direct-before-leak":"direct Storage denial before API warm","direct-warm-leak":"direct Storage denial after API warm",
        "direct-deleted-leak":"direct Storage denial post-delete","api-deleted-cache":"same API photo URL revoked after delete",
        "owner-api-missing":"owner API exact canonical photo GET","owner-api-wrong-hash":"owner API exact canonical photo GET"}
    if scenario!="pass":assert checks[failure_checks[scenario]] is False
    assert report["fixtureCleanup"]=="BYTES_REMOVED_METADATA_PENDING_DURABLE_SCHEDULE"
    if "caller-delete" in events:
        first_delete=events.index("caller-delete")
        assert events[first_delete+1:first_delete+3]==["trusted-get","trusted-list"]
    if scenario=="pass":
        assert checks["A rows unchanged by attacks"] and checks["A bytes unchanged"]
        assert checks["physical bytes gone before metadata purge"]
        assert checks["owner API exact canonical photo GET"] and checks["same API photo URL revoked after delete"]
        assert set(direct_reads)=={(phase,caller,route) for phase in ("before API warm","after API warm","post-delete") for caller in ("A","B","publishable") for route in ("authenticated","ordinary")}
        assert matrix=={**{operation:{"A","B","publishable"} for operation in ("data-write","rpc","upload","overwrite","delete","sign","list","bytes")},"data-read":{"B","publishable"}}
        assert data_write_statuses=={("A",403),("B",403),("publishable",401)}
        assert api_pair_statuses=={("B",404),("publishable",401)}
        assert {(caller,table) for caller,table,*_ in data_read_responses}=={(caller,table) for caller in ("B","publishable") for table in ("captures","capture_photos")}
        for caller,table,result,status,headers,content in data_read_responses:
            assert (result.status_code,list(result.headers.multi_items()),result.content)==(status,headers,content)
            if caller=="B":assert result.status_code==200 and result.headers["content-location"]==f"/{table}?owner_id=eq.{OWNER}&select=%2A"
            else:assert result.status_code==401 and result.json()["code"]=="42501"
