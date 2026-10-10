# 0013. Password vault (Vaultwarden) and ops registry, integrated by metadata only
Date: 2026-10-10
Status: accepted

## Context
The owner wants passwords for services and servers stored encrypted and connected to the knowledge
base, plus reminders for domain expirations and service payments. KB content is indexed, distilled by
a cloud LLM and returned through MCP, so secrets must never enter it (ADR 0005). Vaultwarden/Bitwarden
encrypt every field client-side (including names and URLs); the server cannot read metadata without
the master key. Only the owner uses the vault.

## Decision
- **Vault:** self-hosted Vaultwarden as a Coolify service, reachable over Tailscale only; Bitwarden
  clients on Mac/iPhone/browser. Folders per scope plus `Servers`. SSH keys and recovery codes live there.
- **Disaster recovery:** nightly encrypted vault export to a second provider/region, plus a printed
  emergency kit (master password hint, Tailscale/hosting/registrar recovery codes). The vault must stay
  recoverable when the KB server is dead.
- **KB integration is push from the Mac, metadata only:** a launchd job using the `bw` CLI while the
  vault is unlocked sends item name, URL/host, username, folder, revision date and has-TOTP flag to
  the KB. Weak/reused/old checks run locally on the Mac; only findings (item names + reason) are sent.
  No password, TOTP secret, note, key or hash ever leaves the Mac. The master password never touches the server.
- **MCP:** `where_are_credentials(query)` returns vault item pointers (folder, item name, host, username).
- **Leaked-secret alerts:** when redaction (ADR 0005) finds a password/key in mail or Telegram, the
  Telegram bot alerts: who sent it, where, suggestion to save to vault and rotate.
- **Weekly hygiene report:** old/weak/reused items (from Mac findings), servers/domains/services with no vault item.
- **Ops registry** (structured tables, scoped): servers (from Coolify API + manual), domains, TLS
  certificates, services/subscriptions. Each entry may reference a vault item by name.
  - Domains: daily public registration (RDAP) lookup for expiry; TLS expiry check; alerts at 60/30/7/1 days.
  - Subscriptions: extracted from invoice/receipt emails by distillation (service, amount, cycle, next
    charge, card); alerts before renewals; immediate alert on "payment failed" / "card expiring" emails.
- KB app secrets stay in Coolify env vars (ADR 0009); Infisical is the upgrade path if rotation/sharing is needed.

## Consequences
Vault metadata in the KB is only as fresh as the last Mac push (shown in results). Building the Mac
exporter shares tooling with the macOS meeting app. Subscription detection depends on receipts
reaching an ingested mailbox; services billed elsewhere are added manually.
