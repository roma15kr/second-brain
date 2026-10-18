# Spec Delta

## Purpose

Lets only the owner use the second brain OS, from a laptop or phone, signed in with a passkey, with
the app installable to the home screen and able to send push notifications.

## ADDED Requirements

### Requirement: Only the owner can sign in, with a passkey
The web OS SHALL require sign-in for every page and data request. Sign-in SHALL use a passkey (Face ID, Touch ID, Windows Hello or a security key) registered by the owner; there SHALL be no passwords.

#### Scenario: Not signed in
- **WHEN** anyone opens any page or data URL without a valid session
- **THEN** they see only the sign-in screen and no knowledge-base data

#### Scenario: Passkey sign-in
- **WHEN** the owner signs in with a registered passkey
- **THEN** the Today page opens and the session lasts 30 days on that device

### Requirement: First passkey enrollment is protected
The first passkey SHALL be registrable only with a one-time setup code created on the server; afterwards new passkeys SHALL be added only from an already signed-in session.

#### Scenario: Stranger tries to enroll
- **WHEN** someone without the setup code tries to register a passkey on a fresh installation
- **THEN** registration is refused

### Requirement: Recovery codes
When the first passkey is registered, the system SHALL show 10 single-use recovery codes once; each SHALL sign in exactly once and SHALL then require adding a new passkey.

#### Scenario: Lost phone
- **WHEN** the owner signs in with a recovery code on a new device
- **THEN** access is granted, that code stops working, and the owner is asked to register a passkey

### Requirement: Sessions can be ended everywhere
The owner SHALL be able to see signed-in devices and sign out one or all of them.

#### Scenario: Sign out everywhere
- **WHEN** the owner chooses "Sign out everywhere"
- **THEN** every other device must sign in again before seeing any data

### Requirement: Repeated failed sign-ins are slowed down
The system SHALL lock out a client after 10 failed sign-in or recovery attempts within 10 minutes.

#### Scenario: Guessing recovery codes
- **WHEN** a client submits 10 wrong recovery codes within 10 minutes
- **THEN** further attempts from that client are refused for 10 minutes

### Requirement: Installable app
The web OS SHALL be installable to the home screen / dock on iPhone, Android and desktop browsers and SHALL open full-screen like an app, showing the last loaded pages when offline (read-only) with a clear offline indicator.

#### Scenario: Offline on the phone
- **WHEN** the installed app is opened without a network connection
- **THEN** the last loaded Today page and briefs are shown, marked as offline, and actions are disabled

### Requirement: Push notifications per device
The owner SHALL be able to enable push notifications per device and choose which routines notify; notifications SHALL contain no message content beyond a short headline (e.g. "Morning brief: 3 need your reply") and SHALL open the related page.

#### Scenario: Morning push
- **WHEN** the morning brief is ready and push is enabled on the iPhone
- **THEN** the iPhone shows a notification with the headline, and tapping it opens the brief

#### Scenario: Device removed
- **WHEN** the owner disables push for a device or the browser revokes permission
- **THEN** no further notifications are sent to it
