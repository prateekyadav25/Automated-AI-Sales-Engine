# Integrations

Never place external SDK logic inside domain services.

```text
EmailProvider
  MockEmailProvider
  GmailProvider
  OutlookProvider
```

Same pattern for advertising, voice, calendar, CRM, support, finance, product usage, company/contact/intent data.

MVP: mock email, mock calendar, mock company/contact data. Live adapters are added when credentials exist and must implement the same interface plus an integration health check.
