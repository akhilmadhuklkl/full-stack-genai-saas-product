# Email setup

Forge Review supports a local console adapter and Resend for transactional email.

## Local development

Use the console adapter while developing:

```env
EMAIL_PROVIDER=console
EMAIL_FROM=noreply@example.com
PUBLIC_BASE_URL=http://127.0.0.1:8000
```

Verification and reset links are written to the application logs. Do not use this mode for
real user accounts or production traffic.

## Resend setup

1. Create a Resend account.
2. Create an API key with the minimum permissions needed to send email.
3. Add and verify the domain that will appear in the sender address.
4. Configure the application:

```env
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_...
EMAIL_FROM=Forge Review <noreply@yourdomain.com>
PUBLIC_BASE_URL=https://your-application-domain.example
```

5. Restart the API after changing environment variables.
6. Request an email verification or password reset message.
7. Confirm the link uses the configured `PUBLIC_BASE_URL` and can be consumed only once.

## Safety requirements

- Never commit `RESEND_API_KEY` or place it in frontend code.
- Use a verified sender domain rather than a personal mailbox.
- Keep password-reset and verification messages generic about account existence.
- Monitor delivery failures and rotate the API key if it is exposed.
- Configure `EMAIL_PROVIDER=resend` and a valid API key before using `APP_ENV=production`.

Resend pricing and plan limits can change; check the provider’s current pricing and sending
documentation before selecting a production plan.
