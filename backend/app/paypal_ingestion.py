"""App-owned PayPal postback verification and atomic receipt/read scheduling."""
from datetime import datetime
import hashlib
import re

from fastapi import APIRouter,HTTPException,Request
from starlette.concurrency import run_in_threadpool

from .contracts import Identifier
from .ingestion import MAX_BODY,decode_json
from .jobs import ReadFailure,enqueue_purchase
from .paypal_provider import VERSION,resource_id

router=APIRouter()
CAPTURE_EVENTS={'PAYMENT.CAPTURE.COMPLETED','PAYMENT.CAPTURE.PENDING','PAYMENT.CAPTURE.DENIED',
                'PAYMENT.CAPTURE.REVERSED'}
ORDER_EVENTS={'CHECKOUT.ORDER.APPROVED','CHECKOUT.ORDER.COMPLETED'}


def verification_payload(event,headers,webhook_id):
    if not webhook_id: raise ValueError('Webhook destination missing')
    fields={}
    for field in ('auth_algo','cert_url','transmission_id','transmission_sig','transmission_time'):
        values=headers.getlist('paypal-'+field.replace('_','-'))
        if len(values)!=1 or not values[0] or len(values[0])>500: raise ValueError('Invalid verification header')
        fields[field]=values[0]
    if fields['auth_algo']!='SHA256withRSA': raise ValueError('Unsupported signature algorithm')
    if not re.fullmatch(r'https://api(?:-m)?\.sandbox\.paypal\.com/v1/notifications/certs/CERT-[A-Za-z0-9-]{1,200}',fields['cert_url']):
        raise ValueError('Certificate origin is not sandbox PayPal')
    if not re.fullmatch(r'[A-Za-z0-9-]{1,50}',fields['transmission_id']): raise ValueError('Invalid transmission identity')
    if not re.fullmatch(r'[A-Za-z0-9+/]{1,498}={0,2}',fields['transmission_sig']): raise ValueError('Invalid signature encoding')
    stamp=datetime.fromisoformat(fields['transmission_time'])
    if stamp.utcoffset() is None: raise ValueError('Invalid transmission time')
    # PayPal retries deliveries for days. Remote signature verification and
    # durable event identity handle replay; no five-minute age rejection here.
    return fields|{'webhook_id':webhook_id,'webhook_event':event}


def parse_event(raw):
    event=decode_json(raw)
    if not isinstance(event,dict) or not isinstance(event.get('id'),str) or not re.fullmatch(r'[A-Z0-9-]{1,100}',event['id']):
        raise ValueError('Invalid PayPal envelope')
    kind=event.get('event_type')
    if not isinstance(kind,str) or not re.fullmatch(r'[A-Z0-9_.]{1,100}',kind): raise ValueError('Invalid event type')
    stamp=datetime.fromisoformat(event.get('create_time',''))
    if stamp.utcoffset() is None: raise ValueError('Invalid event time')
    if kind not in CAPTURE_EVENTS|ORDER_EVENTS|{'PAYMENT.CAPTURE.REFUNDED'}:
        return event,'ignored',None,None,None
    if event.get('resource_version')!='2.0': return event,'quarantined',None,None,None
    resource=event.get('resource')
    if not isinstance(resource,dict): raise ValueError('Invalid resource')
    expected='order' if kind in ORDER_EVENTS else 'refund' if kind=='PAYMENT.CAPTURE.REFUNDED' else 'capture'
    if event.get('resource_type')!=expected: return event,'quarantined',None,None,None
    key=resource_id(resource.get('id'))
    lookup=key
    if expected=='refund':
        supplementary=resource.get('supplementary_data',{})
        related=supplementary.get('related_ids',{}) if isinstance(supplementary,dict) else {}
        if not isinstance(related,dict) or not related.get('capture_id'):
            return event,'quarantined','refund',key,None
        lookup=resource_id(related['capture_id'])
    return event,'accepted',expected,key,lookup


def persist(database,workspace,connection,raw,event,state,kind,key,lookup):
    digest=hashlib.sha256(raw).hexdigest()
    with database.transaction(workspace) as cursor:
        cursor.execute('''INSERT INTO inbox(workspace_id,connection_id,event_id,event_type,api_version,raw_body,
            body_digest,state,resource_type,resource_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING RETURNING event_id''',
            (workspace,connection,event['id'],event['event_type'],VERSION,raw,digest,state,kind,key))
        if cursor.fetchone() is None:
            cursor.execute('SELECT body_digest,state FROM inbox WHERE connection_id=%s AND event_id=%s',(connection,event['id']))
            previous=cursor.fetchone()
            if previous['body_digest']!=digest: raise HTTPException(409,'Event identity payload conflict')
            return {'received':True,'duplicate':True,'state':previous['state']}
        if state=='accepted' and lookup:
            if kind=='order':
                cursor.execute('SELECT purchase_id FROM paypal_orders WHERE connection_id=%s AND order_id=%s',(connection,lookup))
            else:
                cursor.execute('''SELECT o.purchase_id FROM paypal_captures c JOIN paypal_orders o
                    USING(workspace_id,connection_id,order_id) WHERE c.connection_id=%s AND c.capture_id=%s''',(connection,lookup))
            row=cursor.fetchone()
            if row: enqueue_purchase(cursor,workspace,connection,row['purchase_id'])
            # An unregistered object stays a receipt; registration and sweeps
            # schedule reads later. No purchase is invented from an event.
    return {'received':True,'duplicate':False,'state':state}


def verify_and_persist(app,workspace,connection,raw,headers):
    try:
        parsed=parse_event(raw)
        event=parsed[0]
        clients=app.state.paypal_webhook_readers
        clients[workspace].verify_webhook(event,headers)
    except (ValueError,TypeError,AttributeError,RecursionError):
        raise HTTPException(400,'Invalid PayPal event or signature') from None
    except ReadFailure:
        raise HTTPException(503,'PayPal verification unavailable; delivery remains retryable') from None
    return persist(app.state.database,workspace,connection,raw,*parsed)


@router.post('/webhooks/paypal/{destination}')
async def receive(destination: Identifier,request: Request):
    workspace=next((ws for ws in request.app.state.settings.paypal if destination==f'paypal_{ws}'),None)
    if workspace is None or not request.app.state.settings.paypal[workspace].webhook_id:
        raise HTTPException(404,'PayPal webhook destination not configured')
    if request.headers.get('content-encoding','identity')!='identity': raise HTTPException(415,'Encoded bodies unsupported')
    if request.headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
        raise HTTPException(415,'JSON event required')
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_BODY: raise HTTPException(413,'Body limit exceeded')
    return await run_in_threadpool(verify_and_persist,request.app,workspace,destination,bytes(raw),request.headers)
