# QuickBooks Production Pages

These files are a minimal static bundle for the URLs Intuit typically asks for
when enabling production access for a private/internal QuickBooks app.

Before deploying them on your org domain, update the placeholders in each file:

- `YOUR ORGANIZATION`
- `finance@example.com`
- `support@example.com`
- `https://your-org.example.com`

Suggested deployment paths:

- `/integrations/quickbooks/privacy`
- `/integrations/quickbooks/terms`
- `/integrations/quickbooks/launch`
- `/integrations/quickbooks/disconnect`
- `/integrations/quickbooks/callback`

All pages share `styles.css`, so keep that file alongside the HTML files when
deploying them to your hosting platform.
