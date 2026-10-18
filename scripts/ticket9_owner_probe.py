"""Explicit paid/private owner gate for an already uploaded, confirmed Capture.

Uses the deployed API and its existing ledger. Never uploads photographs, guesses
measurements or confirms an owner Room. Builder turn must not execute this probe.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import UUID
import httpx


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--authorized-paid-private",action="store_true")
    p.add_argument("--api-url",required=True);p.add_argument("--capture-id",required=True,type=UUID)
    p.add_argument("--reference-id",required=True);p.add_argument("--analyze",action="store_true")
    p.add_argument("--output",required=True,type=Path);a=p.parse_args()
    if not a.authorized_paid_private:p.error("Paid/private authorization is required.")
    token=os.environ.get("FURNITUREOS_CAPTURE_OWNER_JWT","")
    if not token:p.error("Owner JWT must be supplied privately through environment.")
    if a.output.resolve().is_relative_to(Path(__file__).resolve().parent.parent):p.error("External output required.")
    report={"status":"FAIL","kind":"REAL_OWNER_PAID_CAPTURE_PROBE","phone":"UNRUN","tapeReference":"UNRUN",
        "startedAt":datetime.now(timezone.utc).isoformat(),"analysis":[]}
    try:
        with httpx.Client(base_url=a.api_url.rstrip("/"),headers={"Authorization":"Bearer "+token},timeout=300,follow_redirects=False,trust_env=False) as c:
            capture=c.get(f"/api/captures/{a.capture_id}").raise_for_status().json()
            if a.analyze:
                for photo in capture["photos"][:4]:
                    if photo["state"]!="accepted":continue
                    capture=c.post(f"/api/captures/{a.capture_id}/photos/{photo['id']}/analyze",json={"expectedRevision":capture["revision"]}).raise_for_status().json()
                    current=next(x for x in capture["photos"] if x["id"]==photo["id"])
                    report["analysis"].append({"wall":current["primaryWallId"],"status":current["analysisStatus"],"proposalCount":len((current.get("semantics") or {}).get("openings",[]))})
            if capture["state"]!="confirmed":raise ValueError("Owner must review/confirm the Room in the UI first.")
            result=c.post(f"/api/captures/{a.capture_id}/generate",json={"expectedRevision":capture["revision"],"referenceId":a.reference_id}).raise_for_status().json()
            # Do not copy private Room geometry, photos, provider bodies or JWTs into evidence.
            value=result.get("result",{})
            report["generation"]={"status":result["status"],"resultStatus":value.get("status"),"code":value.get("code",result.get("code")),"providerCalls":value.get("providerCalls",0),"usage":value.get("usage"),"confirmedRevision":result.get("confirmedRevision")}
            report["status"]="OBSERVED_OWNER_ASSESSMENT_REQUIRED"
    except Exception as failure:report["failureType"]=type(failure).__name__
    report["finishedAt"]=datetime.now(timezone.utc).isoformat()
    a.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    return 0 if report["status"]=="OBSERVED_OWNER_ASSESSMENT_REQUIRED" else 1

if __name__=="__main__":raise SystemExit(main())
