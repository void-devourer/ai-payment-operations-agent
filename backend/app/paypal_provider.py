"""PayPal sandbox reads and signature verification for investigation.

Only OAuth, order/capture reads and signature verification are supported.
A capture alone does not establish complete reversal history or repair eligibility.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
import os
import re
from threading import Lock
import time

import httpx

from .ingestion import decode_json
from .jobs import ReadFailure

API_BASE='https://api-m.sandbox.paypal.com'
MAX_BODY=1024*1024
RESOURCE=re.compile(r'[A-Z0-9]{8,32}')
STATUSES={'COMPLETED','DECLINED','PARTIALLY_REFUNDED','PENDING','REFUNDED','FAILED'}
VERSION='paypal_orders_v2_payments_v2'


@dataclass(frozen=True)
class PayPalSandboxConnection:
    client_id: str=field(repr=False)
    client_secret: str=field(repr=False)
    merchant_id: str
    environment: str='sandbox'
    webhook_id: str | None=None

    def __post_init__(self):
        if self.environment!='sandbox':
            raise ValueError('Only the PayPal sandbox is supported')
        for value in (self.client_id,self.client_secret):
            if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9._~+=/-]{8,512}',value):
                raise ValueError('PayPal sandbox credentials are missing or invalid')
        if not isinstance(self.merchant_id,str) or not re.fullmatch(r'[A-Z0-9]{13}',self.merchant_id):
            raise ValueError('A sandbox merchant ID is required')
        if self.webhook_id is not None and (not isinstance(self.webhook_id,str) or
                not re.fullmatch(r'[A-Z0-9]{8,50}',self.webhook_id)):
            raise ValueError('An app-owned PayPal webhook ID is required')


def connections_from_env():
    enabled=os.environ.get('PAYPAL_ENABLED','0')
    if enabled not in {'0','1'}:
        raise ValueError('PAYPAL_ENABLED must be 0 or 1')
    if enabled=='0': return {}
    result={}
    for letter in ('A','B'):
        prefix=f'PAYPAL_WORKSPACE_{letter}_'
        fields=('CLIENT_ID','CLIENT_SECRET','MERCHANT_ID','WEBHOOK_ID')
        if any(os.environ.get(prefix+field) for field in fields):
            values=[os.environ.get(prefix+field,'') for field in fields]
            result[f'ws_{letter.lower()}']=PayPalSandboxConnection(*values[:3],
                environment=os.environ.get('PAYPAL_ENVIRONMENT','sandbox'),webhook_id=values[3] or None)
    if not result: raise ValueError('PayPal enabled without a sandbox connection')
    for field in ('merchant_id','client_id','webhook_id'):
        identities=[getattr(item,field) for item in result.values() if getattr(item,field) is not None]
        if len(set(identities))!=len(identities):
            raise ValueError('Each workspace needs a distinct PayPal sandbox seller/app/destination')
    return result


def configure_connections(database,settings):
    for workspace,connection in settings.paypal.items():
        with database.transaction(workspace) as cursor:
            cursor.execute("""INSERT INTO connections(workspace_id,connection_id,account_id,environment,api_version,provider)
                VALUES (%s,%s,%s,'test',%s,'paypal') ON CONFLICT DO NOTHING""",
                (workspace,f'paypal_{workspace}',connection.merchant_id,VERSION))
            cursor.execute('SELECT account_id,environment,api_version,provider FROM connections WHERE connection_id=%s',
                           (f'paypal_{workspace}',))
            if dict(cursor.fetchone())!={'account_id':connection.merchant_id,'environment':'test','api_version':VERSION,'provider':'paypal'}:
                raise ValueError('PayPal connection conflicts with its immutable seller/environment')


@dataclass(frozen=True)
class CaptureFact:
    capture_id: str
    order_id: str
    merchant_id: str
    status: str
    amount_minor: int
    currency: str
    created_at: datetime
    updated_at: datetime
    reversals_complete: bool=field(default=False,init=False)
    settlement_verified: bool=field(default=False,init=False)


def resource_id(value):
    if not isinstance(value,str) or RESOURCE.fullmatch(value) is None:
        raise ValueError('Invalid PayPal resource identifier')
    return value


def require(condition):
    if not condition:
        raise ReadFailure('paypal_capture_scope_or_shape',False)


def normalize_capture(body,capture_id,expected_order_id,merchant_id):
    """Retain provider status and gross amount; never infer refund/dispute absence."""
    require(isinstance(body,dict) and body.get('id')==capture_id)
    payee=body.get('payee')
    supplementary=body.get('supplementary_data')
    require(isinstance(payee,dict) and payee.get('merchant_id')==merchant_id)
    require(isinstance(supplementary,dict))
    related=supplementary.get('related_ids')
    require(isinstance(related,dict) and related.get('order_id')==expected_order_id)
    status=body.get('status')
    require(isinstance(status,str) and status in STATUSES)
    amount=body.get('amount')
    require(isinstance(amount,dict) and amount.get('currency_code')=='USD')
    value=amount.get('value')
    require(isinstance(value,str) and re.fullmatch(r'[0-9]{1,13}(?:\.[0-9]{1,2})?',value) is not None)
    minor=int(Decimal(value)*100)
    require(0<minor<=10**12)
    try:
        created=datetime.fromisoformat(body['create_time'])
        updated=datetime.fromisoformat(body['update_time'])
        require(created.tzinfo is not None and updated.tzinfo is not None)
        created,updated=created.astimezone(UTC),updated.astimezone(UTC)
        require(created<=updated<=datetime.now(UTC))
    except (KeyError,ValueError,TypeError,OverflowError):
        raise ReadFailure('paypal_capture_scope_or_shape',False) from None
    return CaptureFact(capture_id,expected_order_id,merchant_id,status,minor,'usd',created,updated)


class PayPalSandboxClient:
    def __init__(self,connection: PayPalSandboxConnection,http: httpx.Client,*,clock=time.monotonic):
        self.connection,self.http,self.clock=connection,http,clock
        self._access_token=''
        self._token_until=0
        self._token_lock=Lock()
        self.before_request=None

    def _json(self,method,path,**kwargs):
        # Reject arbitrary paths even inside this private helper. HATEOAS links
        # and caller-supplied origins never select the request destination.
        allowed=(method=='POST' and path in ('/v1/oauth2/token','/v1/notifications/verify-webhook-signature')) or (
            method=='GET' and any(path.startswith(prefix) and RESOURCE.fullmatch(path.removeprefix(prefix)) is not None
                for prefix in ('/v2/payments/captures/','/v2/checkout/orders/')))
        if not allowed:
            raise ValueError('Unsupported PayPal operation')
        if self.before_request is not None: self.before_request()
        started=self.clock()
        try:
            with self.http.stream(method,API_BASE+path,timeout=5,follow_redirects=False,**kwargs) as response:
                if response.status_code==401:
                    raise ReadFailure('paypal_authentication_failed',False)
                if response.status_code==403:
                    raise ReadFailure('paypal_permission_denied',False)
                if response.status_code==404:
                    raise ReadFailure('paypal_resource_missing',False)
                if response.status_code==429:
                    delay=response.headers.get('Retry-After','2')
                    seconds=min(300,max(1,int(delay))) if re.fullmatch(r'[0-9]{1,9}',delay) else 2
                    raise ReadFailure('paypal_rate_limited',delay=seconds)
                if response.status_code>=500:
                    raise ReadFailure('paypal_unavailable')
                if response.status_code!=200:
                    raise ReadFailure('paypal_unexpected_response',False)
                raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>MAX_BODY:
                        raise ReadFailure('paypal_response_budget',False)
                    if self.clock()-started>10:
                        raise ReadFailure('paypal_response_timeout')
                value=decode_json(raw)
                if not isinstance(value,dict):
                    raise ValueError()
                return value
        except httpx.RequestError:
            raise ReadFailure('paypal_network_error') from None
        except (ValueError,RecursionError):
            raise ReadFailure('paypal_invalid_json',False) from None

    def _token(self):
        with self._token_lock:
            if self._access_token and self.clock()<self._token_until:
                return self._access_token
            # Expiry begins before the network call so latency cannot extend TTL.
            requested_at=self.clock()
            body=self._json('POST','/v1/oauth2/token',
                auth=httpx.BasicAuth(self.connection.client_id,self.connection.client_secret),
                data={'grant_type':'client_credentials'},headers={'Accept':'application/json'})
            token,seconds=body.get('access_token'),body.get('expires_in')
            token_type=body.get('token_type')
            if (not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9._~+=/-]{1,4096}',token)
                    or not isinstance(token_type,str) or token_type.lower()!='bearer'
                    or type(seconds) is not int or not 0<seconds<=86400):
                raise ReadFailure('paypal_invalid_token',False)
            self._access_token=token
            self._token_until=requested_at+max(0,seconds-30)
            return token

    def authorized(self,method,path,**kwargs):
        for attempt in range(2):
            token=self._token()
            try:
                body=self._json(method,path,headers={'Accept':'application/json','Authorization':'Bearer '+token},**kwargs)
            except ReadFailure as error:
                if error.code!='paypal_authentication_failed' or attempt==1:
                    raise
                with self._token_lock:
                    if self._access_token==token:
                        self._access_token=''; self._token_until=0
                continue
            return body
        raise ReadFailure('paypal_authentication_failed',False)

    def capture(self,capture_id: str,expected_order_id: str) -> CaptureFact:
        capture_id,expected_order_id=resource_id(capture_id),resource_id(expected_order_id)
        body=self.authorized('GET',f'/v2/payments/captures/{capture_id}')
        return normalize_capture(body,capture_id,expected_order_id,self.connection.merchant_id)

    def order(self,order_id,purchase):
        from .paypal_investigation import normalize_order
        order_id=resource_id(order_id)
        return normalize_order(self.authorized('GET',f'/v2/checkout/orders/{order_id}'),order_id,
                               purchase,self.connection.merchant_id)

    def verify_webhook(self,event,headers):
        from .paypal_ingestion import verification_payload
        payload=verification_payload(event,headers,self.connection.webhook_id)
        result=self.authorized('POST','/v1/notifications/verify-webhook-signature',json=payload)
        if result.get('verification_status')!='SUCCESS':
            raise ValueError('Invalid PayPal signature')
