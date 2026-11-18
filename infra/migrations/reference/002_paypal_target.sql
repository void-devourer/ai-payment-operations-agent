ALTER TABLE orders ALTER COLUMN payment_intent_id DROP NOT NULL;
ALTER TABLE orders ADD COLUMN paypal_order_id text CHECK(paypal_order_id ~ '^[A-Z0-9]{8,32}$');
ALTER TABLE orders ADD CONSTRAINT order_provider_identity CHECK (
    (payment_intent_id IS NOT NULL AND paypal_order_id IS NULL) OR
    (payment_intent_id IS NULL AND paypal_order_id IS NOT NULL)
);
