-- Passkeys are bound to the web OS domain (relying party). Keeping the domain per credential lets
-- the owner enrol again with a setup code after the web OS moves to a new domain.
ALTER TABLE webauthn_credentials ADD COLUMN rp_id text NOT NULL DEFAULT '';
