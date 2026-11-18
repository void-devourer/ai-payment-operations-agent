"""Server-authenticated immutable purchase/order/capture bindings."""
from fastapi import APIRouter,HTTPException,Request
from typing import Annotated
from pydantic import Field

from .contracts import Contract,Identifier
from .jobs import enqueue_purchase
from .security import service_workspace

router=APIRouter()
PayPalID=Annotated[str,Field(strict=True,pattern=r'^[A-Z0-9]{8,32}$')]


class OrderRegistration(Contract):
    order_id: PayPalID


class CaptureRegistration(OrderRegistration):
    capture_id: PayPalID


def purchase_connection(cursor,workspace,purchase_id,settings):
    cursor.execute('SELECT connection_id FROM purchases WHERE purchase_id=%s',(purchase_id,))
    row=cursor.fetchone()
    if row is None: raise HTTPException(409,'Register purchase before its PayPal records')
    if workspace not in settings.paypal or row['connection_id']!=f'paypal_{workspace}':
        raise HTTPException(403,'PayPal connection/workspace mismatch')
    return row['connection_id']


def invalidate(cursor,workspace,purchase,connection):
    # Jobs then head is the same lock order as evidence publication.
    enqueue_purchase(cursor,workspace,connection,purchase)
    cursor.execute('UPDATE evidence_heads SET generation=generation+1,observation_id=NULL WHERE purchase_id=%s',(purchase,))


@router.post('/api/purchases/{purchase_id}/paypal-orders')
def register_order(purchase_id: Identifier,body: OrderRegistration,request: Request):
    workspace=service_workspace(request,'registration')
    with request.app.state.database.transaction(workspace) as cursor:
        connection=purchase_connection(cursor,workspace,purchase_id,request.app.state.settings)
        cursor.execute('INSERT INTO paypal_orders VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING order_id',
                       (workspace,purchase_id,connection,body.order_id))
        inserted=cursor.fetchone() is not None
        cursor.execute('SELECT purchase_id FROM paypal_orders WHERE connection_id=%s AND order_id=%s',(connection,body.order_id))
        if cursor.fetchone()['purchase_id']!=purchase_id: raise HTTPException(409,'Order is already bound to another purchase')
        if inserted: invalidate(cursor,workspace,purchase_id,connection)
    return {'registered':True,'order_id':body.order_id}


@router.post('/api/purchases/{purchase_id}/paypal-captures')
def register_capture(purchase_id: Identifier,body: CaptureRegistration,request: Request):
    workspace=service_workspace(request,'registration')
    with request.app.state.database.transaction(workspace) as cursor:
        connection=purchase_connection(cursor,workspace,purchase_id,request.app.state.settings)
        cursor.execute('SELECT purchase_id FROM paypal_orders WHERE connection_id=%s AND order_id=%s',(connection,body.order_id))
        row=cursor.fetchone()
        if row is None or row['purchase_id']!=purchase_id: raise HTTPException(409,'Register this purchase/order before its capture')
        cursor.execute('INSERT INTO paypal_captures VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING capture_id',
                       (workspace,connection,body.order_id,body.capture_id))
        inserted=cursor.fetchone() is not None
        cursor.execute('SELECT order_id FROM paypal_captures WHERE connection_id=%s AND capture_id=%s',(connection,body.capture_id))
        if cursor.fetchone()['order_id']!=body.order_id: raise HTTPException(409,'Capture is already bound to another order')
        if inserted: invalidate(cursor,workspace,purchase_id,connection)
    return {'registered':True,'capture_id':body.capture_id,'order_id':body.order_id}
