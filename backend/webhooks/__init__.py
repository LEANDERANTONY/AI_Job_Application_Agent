"""Webhook handlers for external payment / event sources.

Currently houses the Lemon Squeezy subscription webhook. Future
processors (Stripe, Razorpay) would land in sibling modules; the
common shape is "HMAC verify -> idempotency check -> event-to-state
mapping -> 2xx response".
"""
