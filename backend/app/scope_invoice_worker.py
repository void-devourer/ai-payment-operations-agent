"""Leased invoice creation with fencing and explicit uncertain-write recovery.

A process loss after claiming an external write is deliberately uncertain. An
expired creation lease can never trigger a second financial draft creation.
"""
from datetime import UTC, datetime
import uuid

from .scope.models import connection_digest
from .scope import store


def run_once(app, workspace):
    from .scope_invoicing import InvoiceError, activate_invoice, create_draft
    database = app.state.database
    with database.transaction(workspace) as cursor:
        # An expired lease may have reached PayPal. Record the uncertainty and
        # finish the job without dispatching another create request.
        cursor.execute('''SELECT j.invoice_id,j.operation,i.project_id,i.provider FROM scope_invoice_jobs j JOIN scope_invoices i
            USING(workspace_id,invoice_id) WHERE j.state='leased' AND j.lease_until<=now()
            ORDER BY j.created_at,j.invoice_id LIMIT 1''')
        expired = cursor.fetchone()
        if expired:
            store.project(cursor, expired['project_id'], lock=True)
            cursor.execute('''SELECT j.invoice_id,j.operation,i.project_id,i.provider FROM scope_invoice_jobs j JOIN scope_invoices i
                USING(workspace_id,invoice_id) WHERE j.invoice_id=%s AND j.state='leased' AND j.lease_until<=now()
                FOR UPDATE OF j,i''', (expired['invoice_id'],))
            expired = cursor.fetchone()
            if expired is None:
                return True
            if expired['provider'] == 'local':
                cursor.execute("UPDATE scope_invoice_jobs SET state='queued',lease_token=NULL,lease_until=NULL WHERE invoice_id=%s", (expired['invoice_id'],))
                cursor.execute("UPDATE scope_invoices SET status='draft',last_error=NULL,updated_at=now() WHERE invoice_id=%s", (expired['invoice_id'],))
                return True
            cursor.execute("UPDATE scope_invoice_jobs SET state='unknown',lease_token=NULL,lease_until=NULL WHERE invoice_id=%s", (expired['invoice_id'],))
            cursor.execute("UPDATE scope_invoices SET status='outcome_unknown',last_error=%s,updated_at=now() WHERE invoice_id=%s",
                ('activation_outcome_unknown' if expired['operation'] == 'activate' else 'worker_stopped_during_create', expired['invoice_id']))
            store.event(cursor, workspace, expired['project_id'], 'invoice_unknown', 'Invoice creation was interrupted; verify its outcome before any further billing')
            return True
        cursor.execute('''SELECT i.*,j.operation FROM scope_invoice_jobs j JOIN scope_invoices i USING(workspace_id,invoice_id)
            WHERE j.state='queued' ORDER BY j.created_at,j.invoice_id LIMIT 1''')
        invoice = cursor.fetchone()
        if invoice is None:
            return False
        store.project(cursor, invoice['project_id'], lock=True)
        # The row may have completed create and been explicitly re-queued for
        # activation while this worker waited. Re-read the operation and invoice
        # together under the lock; never dispatch the pre-lock candidate data.
        cursor.execute('''SELECT i.*,j.operation FROM scope_invoice_jobs j JOIN scope_invoices i USING(workspace_id,invoice_id)
            WHERE j.invoice_id=%s AND j.state='queued' FOR UPDATE OF j,i''', (invoice['invoice_id'],))
        invoice = cursor.fetchone()
        if invoice is None:
            return True
        lease = uuid.uuid4().hex
        cursor.execute("UPDATE scope_invoice_jobs SET state='leased',lease_token=%s,lease_until=now()+interval '45 seconds' WHERE invoice_id=%s", (lease, invoice['invoice_id']))
        cursor.execute("UPDATE scope_invoices SET status='creating',updated_at=now() WHERE invoice_id=%s", (invoice['invoice_id'],))
    result = None
    failure = None
    try:
        if invoice['provider'] == 'local':
            result = {'provider_invoice_id': 'local_' + invoice['invoice_id'], 'status': 'unpaid',
                      'amount_minor': invoice['amount_minor'], 'currency': invoice['currency'], 'payment_url': None}
        else:
            connection = app.state.settings.paypal.get(workspace)
            if connection is None:
                raise InvoiceError('paypal_not_configured')
            if connection_digest(connection) != invoice['provider_connection_digest']:
                raise InvoiceError('paypal_connection_changed')
            if invoice['operation'] == 'activate':
                result = activate_invoice(connection, app.state.http, invoice['provider_invoice_id'], invoice['payload'])
            else:
                result = create_draft(connection, app.state.http, invoice['payload'], 'scope-invoice:' + invoice['invoice_id'])
        if not isinstance(result, dict) or type(result.get('amount_minor')) is not int or result['amount_minor'] != invoice['amount_minor'] or result.get('currency') != invoice['currency'] or not isinstance(result.get('provider_invoice_id'), str) or not result['provider_invoice_id'] or result.get('status') not in ('draft', 'unpaid', 'paid'):
            raise InvoiceError('invoice_result_mismatch', uncertain=invoice['provider'] != 'local')
        if invoice['operation'] == 'activate' and (result['provider_invoice_id'] != invoice['provider_invoice_id'] or result['status'] not in ('unpaid', 'paid') or (result['status'] == 'unpaid' and not result.get('payment_url'))):
            raise InvoiceError('invoice_activation_result_mismatch', uncertain=True)
    except InvoiceError as error:
        failure = error
    except Exception:
        # Unexpected failures after dispatch are not evidence the write failed.
        failure = InvoiceError('invoice_worker_failed', uncertain=invoice['provider'] != 'local')
    with database.transaction(workspace) as cursor:
        store.project(cursor, invoice['project_id'], lock=True)
        cursor.execute('''SELECT j.state,j.lease_token,j.lease_until FROM scope_invoice_jobs j
            WHERE invoice_id=%s FOR UPDATE''', (invoice['invoice_id'],))
        current = cursor.fetchone()
        if current['state'] != 'leased' or current['lease_token'] != lease or current['lease_until'] <= datetime.now(UTC):
            return True
        if failure:
            uncertain = failure.uncertain
            cursor.execute('UPDATE scope_invoice_jobs SET state=%s,lease_token=NULL,lease_until=NULL WHERE invoice_id=%s',
                           ('unknown' if uncertain else 'failed', invoice['invoice_id']))
            error_code = 'activation_outcome_unknown' if uncertain and invoice['operation'] == 'activate' else failure.code
            cursor.execute('UPDATE scope_invoices SET status=%s,last_error=%s,updated_at=now() WHERE invoice_id=%s',
                           ('outcome_unknown' if uncertain else 'failed', error_code, invoice['invoice_id']))
            store.event(cursor, workspace, invoice['project_id'], 'invoice_unknown' if uncertain else 'invoice_failed',
                        'Invoice creation outcome needs review; no new create will be attempted' if uncertain else 'Invoice creation failed before a confirmed result; review configuration and provider response')
        else:
            cursor.execute("UPDATE scope_invoice_jobs SET state='done',lease_token=NULL,lease_until=NULL WHERE invoice_id=%s", (invoice['invoice_id'],))
            cursor.execute('''UPDATE scope_invoices SET provider_invoice_id=%s,status=%s,payment_url=%s,last_error=NULL,updated_at=now()
                WHERE invoice_id=%s''', (result['provider_invoice_id'], result['status'], result.get('payment_url'), invoice['invoice_id']))
            kind = 'invoice_activated' if invoice['operation'] == 'activate' else 'invoice_created'
            text = 'PayPal sandbox payment link enabled; no invoice email sent' if invoice['operation'] == 'activate' else (
                'Local demo invoice created' if invoice['provider'] == 'local' else 'PayPal sandbox draft created; no invoice email sent')
            store.event(cursor, workspace, invoice['project_id'], kind, text)
    return True
