"""Authenticated raw simulator receipts; no event snapshot becomes current evidence."""

import hashlib
import hmac
import json
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from .contracts import Identifier
from .jobs import enqueue

router = APIRouter()
MAX_BODY = 1024 * 1024
identifier = TypeAdapter(Identifier)
HANDLED = {"payment_intent.succeeded", "payment_intent.processing", "payment_intent.payment_failed",
           "payment_intent.requires_capture", "payment_intent.canceled", "charge.refunded",
           "charge.dispute.created", "charge.dispute.closed", "refund.updated"}


def verify_signature(raw, header, secret, now=None):
    if len(header) > 2048:
        raise ValueError("invalid_signature")
    pieces = [part.split("=",1) for part in header.split(",")]
    stamps = [value for pair in pieces if len(pair)==2 for key,value in [pair] if key=="t"]
    signatures = [value for pair in pieces if len(pair)==2 for key,value in [pair] if key=="v1"]
    if len(stamps)!=1 or not stamps[0].isdigit() or len(stamps[0])>12:
        raise ValueError("invalid_signature")
    timestamp = int(stamps[0])
    if abs((time.time() if now is None else now)-timestamp)>300:
        raise ValueError("signature_expired")
    expected = hmac.new(secret.encode(),stamps[0].encode()+b"."+raw,hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected,signature) for signature in signatures):
        raise ValueError("invalid_signature")


def decode_json(raw):
    def unique_object(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique_object,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError("invalid_json")))


def parse_event(raw, workspace):
    event=decode_json(raw)
    if not isinstance(event,dict) or event.get("object")!="event":
        raise ValueError("invalid_envelope")
    identifier.validate_python(event.get("id"))
    if event.get("account")!=f"sim_acct_{workspace}" or event.get("livemode") is not False:
        raise ValueError("scope_mismatch")
    for field in ("type","api_version"):
        if not isinstance(event.get(field),str) or not 1<=len(event[field])<=100:
            raise ValueError("invalid_envelope")
    if type(event.get("created")) is not int or event["created"]<0:
        raise ValueError("invalid_envelope")
    if event["api_version"]!="simulator.v1":
        return event,"quarantined",None
    if event["type"] not in HANDLED:
        return event,"ignored",None
    resource = event.get("data",{}).get("object",{})
    intent = resource.get("id") if event["type"].startswith("payment_intent.") else resource.get("payment_intent")
    identifier.validate_python(intent)
    return event,"accepted",intent


def persist_receipt(database, workspace, connection, raw, event, state, intent):
    body_digest = hashlib.sha256(raw).hexdigest()
    with database.transaction(workspace) as cursor:
        cursor.execute("""INSERT INTO inbox(workspace_id,connection_id,event_id,event_type,api_version,
            raw_body,body_digest,payment_intent_id,state) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING RETURNING event_id""",
            (workspace,connection,event["id"],event["type"],event["api_version"],raw,body_digest,intent,state))
        inserted = cursor.fetchone() is not None
        if not inserted:
            cursor.execute("SELECT body_digest,state FROM inbox WHERE connection_id=%s AND event_id=%s", (connection,event["id"]))
            old = cursor.fetchone()
            if old["body_digest"]!=body_digest:
                raise HTTPException(409,"Event identity payload conflict")
            return {"received":True,"duplicate":True,"state":old["state"]}
        if state=="accepted":
            enqueue(cursor,workspace,connection,intent)
    return {"received":True,"duplicate":False,"state":state}


@router.post("/webhooks/simulator/{destination}")
async def receive(destination: Identifier, request: Request):
    settings = request.app.state.settings
    workspace = next((ws for ws in settings.keys if destination==f"sim_{ws}"),None)
    if workspace is None:
        raise HTTPException(404,"Destination not configured")
    if request.headers.get("content-encoding", "identity")!="identity":
        raise HTTPException(415,"Encoded bodies unsupported")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_BODY:
            raise HTTPException(413,"Body limit exceeded")
    try:
        verify_signature(bytes(raw),request.headers.get("Simulator-Signature",""),settings.keys[workspace]["webhook"])
        event,state,intent = parse_event(bytes(raw),workspace)
    except (ValueError,TypeError,AttributeError,ValidationError,RecursionError):
        raise HTTPException(400,"Invalid signed event") from None
    return await run_in_threadpool(persist_receipt,request.app.state.database,workspace,destination,bytes(raw),event,state,intent)


@router.post("/webhooks/stripe/{destination}")
async def receive_stripe(destination: Identifier,request: Request):
    settings=request.app.state.settings
    workspace=next((ws for ws in settings.stripe if destination==f"stripe_{ws}"),None)
    if workspace is None:
        raise HTTPException(404,"Stripe destination not configured")
    if request.headers.get("content-encoding","identity")!="identity":
        raise HTTPException(415,"Encoded bodies unsupported")
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_BODY:
            raise HTTPException(413,"Body limit exceeded")
    try:
        from .stripe_provider import parse_stripe_event
        connection=settings.stripe[workspace]
        verify_signature(bytes(raw),request.headers.get("Stripe-Signature",""),connection.webhook_secret)
        event,state,intent=parse_stripe_event(bytes(raw),connection)
    except (ValueError,TypeError,AttributeError,ValidationError,RecursionError):
        raise HTTPException(400,"Invalid signed Stripe event") from None
    return await run_in_threadpool(persist_receipt,request.app.state.database,workspace,destination,bytes(raw),event,state,intent)
