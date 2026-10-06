# Diagnose email that is not arriving

**Goal:** find out why a receipt, digest or OTP email did not reach someone.

## In development

Development never sends real email; everything goes to Mailpit at <http://localhost:8025>. If it is
not there, check that the Mailpit container is running (`mise run dev:mailpit`).

## In production

Run the read-only diagnostic:

```bash
mise run email:diagnose:prod
```

It reports, without sending anything or changing any Resend state:

1. which sender and recipient variables are set (values masked);
2. every domain on the Resend account and whether it is verified — an unverified `negolah.my`
   means Resend accepts the send and never delivers it;
3. the most recent outbound emails and their delivery status (delivered, bounced, rejected).

## What to look at next

- **Never attempted:** check the API logs and Sentry for the send call. Unread digests only go out
  five minutes after the seller's first unanswered message, and not at all if the buyer opened
  the chat ([Background work](../workers/README.md)).
- **Bounced or rejected:** a recipient problem, not ours. The address is in the Resend log.
- **Delivered but not seen:** spam folder; check SPF and DMARC ([ADR-0014](../adr/0014-cloudflare-security-posture-hardening.md)).

Background: [ADR-0012](../adr/0012-transactional-email-sender-and-alerting.md).
