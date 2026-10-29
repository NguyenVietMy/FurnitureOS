"""Actual concurrent public RPC transactions; no second persistence model."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
import subprocess
import time
from uuid import uuid4
import pytest
from backend_tests.local_saved_database import LocalSupabase, PSQL, sql, literal


def commit_call(owner, key, source, document):
    source={'sessionExpiresAt':time.time()+1800,**source}
    canonical = json.dumps(document, sort_keys=True, separators=(',', ':'))
    return ('select public.saved_design_commit('+','.join([
        literal(owner),'true',literal(key),literal(sha256(key.encode()).hexdigest()),literal('local-source'), '1',
        literal(canonical),literal(sha256(canonical.encode()).hexdigest()),literal(json.dumps(source))+'::jsonb'])+');')


def owner_operation(owner, expression):
    return f"set local role authenticated; set local request.jwt.claim.sub={literal(owner)}; set local request.jwt.claims='{{\"is_anonymous\":true}}'; {expression}"


def contend(first_operation, second_operation, *, expire_after_wait=None):
    """Keep transaction one open until transaction two is observed waiting."""
    sql('select 1;')  # Explicit local-database gate, including skip without a local port.
    base=[str(PSQL),'-X','-qAt','-h','127.0.0.1','-p',os.environ['LOCAL_TEST_POSTGRES_PORT'],'-U','postgres','-d','ticket15','-v','ON_ERROR_STOP=1']
    first=subprocess.Popen(base,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    marker='race-'+str(uuid4())
    second=subprocess.Popen(base,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    try:
        first.stdin.write("begin; "+first_operation+" select 'LOCK-HELD';\n"); first.stdin.flush()
        for _ in range(5):
            line=first.stdout.readline()
            if 'LOCK-HELD' in line:break
            if not line:raise AssertionError(first.stderr.read())
        else:raise AssertionError('first transaction did not acquire its lock')
        second.stdin.write('set application_name='+literal(marker)+'; begin; '+second_operation+' commit;\n\\q\n'); second.stdin.flush();second.stdin.close()
        blocked=False
        for _ in range(80):
            observed=sql(f"select count(*) from pg_stat_activity where application_name={literal(marker)} and wait_event_type='Lock';").stdout.strip()
            if observed=='1':blocked=True;break
            time.sleep(.02)
        assert blocked, 'second actual connection never contended with transaction one'
        if expire_after_wait is not None:
            assert sql(f"select count(*) from pg_stat_activity where application_name={literal(marker)} and xact_start<to_timestamp({expire_after_wait});").stdout.strip()=='1', 'save transaction must begin before expiry'
            deadline=time.monotonic()+10
            while sql(f'select clock_timestamp()>to_timestamp({expire_after_wait});').stdout.strip()!='t':
                assert time.monotonic()<deadline,'controlled expiry did not arrive'
                time.sleep(.02)
        first.stdin.write('commit;\n\\q\n'); first.stdin.flush();first.stdin.close()
        first.wait(timeout=10);second.wait(timeout=10)
        output,error=second.stdout.read(),second.stderr.read()
        assert first.returncode==0, first.stderr.read()
        return second.returncode,output,error
    finally:
        for process in (first,second):
            if process.poll() is None:process.kill();process.wait(timeout=5)


@pytest.mark.parametrize('save_first',[False,True])
def test_capture_save_delete_commit_order_is_atomic(save_first):
    boundary=LocalSupabase();owner=boundary.owner;capture=str(uuid4());lease=str(uuid4());key='race-capture-'+str(uuid4())
    sql(f"insert into public.captures(id,owner_id,state,confirmed_revision,room_hash,validated_room,draft) values({literal(capture)},{literal(owner)},'confirmed',1,repeat('a',64),'{{}}','{{\"roomType\":\"bedroom\"}}'); insert into private.capture_operations(id,owner_id,capture_id,revision,kind,expires_at) values({literal(lease)},{literal(owner)},{literal(capture)},1,'session',now()+interval '5 minutes');")
    document={'schemaVersion':1,'catalogueVersion':'controlled-sql','status':'solved','roomType':'bedroom','room':{},'capture':{'id':capture,'confirmedRevision':1,'roomHash':'a'*64}}
    save="set local role service_role; "+commit_call(owner,key,{'kind':'capture','captureId':capture,'revision':1,'roomHash':'a'*64,'lease':lease},document)
    delete=owner_operation(owner,f"select public.capture_user_operation('delete',{literal(capture)},1);")
    code,_,error=contend(save if save_first else delete,delete if save_first else save)
    if save_first:assert code==0,error
    else:assert code!=0 and 'not-found' in error
    assert sql(f'select count(*) from public.saved_designs where owner_id={literal(owner)};').stdout.strip()==('1' if save_first else '0')


@pytest.mark.parametrize('save_first',[False,True])
def test_saved_source_save_delete_commit_order_is_atomic(save_first):
    boundary=LocalSupabase();owner=boundary.owner
    document={'schemaVersion':1,'catalogueVersion':'controlled-sql','status':'solved','roomType':'bedroom'}
    source=json.loads(sql('begin; set local role service_role; '+commit_call(owner,'initial-saved-source',{'kind':'fixture'},document)+' commit;').stdout)
    save='set local role service_role; '+commit_call(owner,'independent-new-copy',{'kind':'saved','id':source['id'],'digest':source['digest']},document)
    delete=owner_operation(owner,f"select public.saved_design_user('delete',{literal(source['id'])});")
    code,_,error=contend(save if save_first else delete,delete if save_first else save)
    if save_first:assert code==0,error
    else:assert code!=0 and 'not-found' in error
    assert sql(f"select count(*) from public.saved_designs where owner_id={literal(owner)} and deleted_at is null;").stdout.strip()==('1' if save_first else '0')


@pytest.mark.parametrize('capacity',[100,3100])
def test_last_quota_slot_is_serialized_across_actual_connections(capacity):
    boundary=LocalSupabase();owner=boundary.owner
    document={'schemaVersion':1,'catalogueVersion':'controlled-sql','status':'solved','roomType':'bedroom'}
    if capacity==100:
        operation=commit_call(owner,"quota-seed-'||i||'",{'kind':'fixture'},document).replace("'quota-seed-''||i||'''","'quota-seed-'||i")
        sql(f'begin; set local role service_role; do $$begin for i in 1..99 loop perform '+operation.removeprefix('select ').rstrip(';')+'; end loop; end$$; commit;')
    else:
        sql(f"insert into public.saved_designs(owner_id,idempotency_key,request_hash,created_at,deleted_at,purge_at) select {literal(owner)},'receipt-seed-'||i,repeat('a',64),now()-interval '2 hours',now()-interval '2 hours',now()+interval '23 hours' from generate_series(1,3099) i;")
    first='set local role service_role; '+commit_call(owner,'last-slot-first',{'kind':'fixture'},document)
    second='set local role service_role; '+commit_call(owner,'last-slot-second',{'kind':'fixture'},document)
    code,_,error=contend(first,second)
    assert code!=0 and 'quota' in error
    assert sql(f'select count(*) from public.saved_designs where owner_id={literal(owner)};').stdout.strip()==str(capacity)


@pytest.mark.parametrize('expire',['capture','lease','session'])
def test_commit_waiting_past_authority_expiry_never_publishes(expire):
    boundary=LocalSupabase();owner=boundary.owner;capture=str(uuid4());lease=str(uuid4())
    expiry=float(sql("select extract(epoch from clock_timestamp()+interval '3 seconds');").stdout)
    capture_expiry=f'to_timestamp({expiry})' if expire=='capture' else "clock_timestamp()+interval '24 hours'"
    sql(f"insert into public.captures(id,owner_id,created_at,expires_at,state,confirmed_revision,room_hash,validated_room,draft) select {literal(capture)},{literal(owner)},expiry-interval '24 hours',expiry,'confirmed',1,repeat('a',64),'{{}}','{{\"roomType\":\"bedroom\"}}' from (select {capture_expiry} as expiry) v;")
    lease_expiry=f'to_timestamp({expiry})' if expire=='lease' else "clock_timestamp()+interval '5 minutes'"
    sql(f"insert into private.capture_operations(id,owner_id,capture_id,revision,kind,expires_at) values({literal(lease)},{literal(owner)},{literal(capture)},1,'session',{lease_expiry});")
    document={'schemaVersion':1,'catalogueVersion':'controlled-sql','status':'solved','roomType':'bedroom','room':{},'capture':{'id':capture,'confirmedRevision':1,'roomHash':'a'*64}}
    source={'kind':'capture','captureId':capture,'revision':1,'roomHash':'a'*64,'lease':lease}
    if expire=='session':source={'kind':'fixture','sessionExpiresAt':expiry}
    save='set local role service_role; '+commit_call(owner,'wait-expiry-key',source,document)
    lock=f'select pg_advisory_xact_lock(hashtextextended({literal(owner)},0));'
    code,_,error=contend(lock,save,expire_after_wait=expiry)
    assert code!=0 and ('not-found' in error or 'lease-expired' in error),error
    assert sql(f'select count(*) from public.saved_designs where owner_id={literal(owner)};').stdout.strip()=='0'
