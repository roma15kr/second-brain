# Spec Delta

## Purpose

What the server offers paired recorder devices beyond uploads: text forms of dictation, optional
cloud transcription of uploaded tracks, and the figures that show whether recording works and
what it costs.

## ADDED Requirements

### Requirement: Dictation for devices with OpenAI
A paired device SHALL be able to send dictated audio and receive the text transcribed by OpenAI, as said, cleaned or structured (the same forms as dictation in the web OS); the audio SHALL not be kept after transcription, the text SHALL be redacted before storage, counted against the AI budget, and listed in the dictation history. The device token SHALL still not read anything else from the knowledge base.

#### Scenario: Structured dictation from the Mac
- **WHEN** the Mac app sends a two-minute dictation and asks for the structured form
- **THEN** it receives the summary, sections, decisions and actions, and the dictation appears in the web OS history without its audio

#### Scenario: Over budget
- **WHEN** the monthly AI budget is used up
- **THEN** the device receives the text as said with a note that cleaning needs budget

### Requirement: Cloud transcription of uploaded tracks
For a recording whose audio was uploaded, a device SHALL be able to request cloud transcription by the server's configured provider (OpenAI or Groq), optionally with speaker separation (OpenAI); the server SHALL transcribe the tracks, store the transcript like one delivered by the device, record the cost, and process the recording as usual.

#### Scenario: Provider switched
- **WHEN** the server's call provider is set to Groq and a recording is uploaded for cloud transcription
- **THEN** both tracks are transcribed by Groq, "me" / "others" labels are kept, and the cost is recorded

#### Scenario: Requested for a team meeting
- **WHEN** the Mac requests cloud transcription for an uploaded 60-minute recording
- **THEN** the transcript with separate speakers is stored, its cost is recorded, and the summary and actions follow

### Requirement: Meetings around now for devices
A paired device SHALL be able to read the owner's calendar meetings within 12 hours of now — only id, title, start, end, and whether it is in progress — to offer them when a recording starts; nothing else from the knowledge base SHALL be readable with a device token.

#### Scenario: Offer at recording start
- **WHEN** the Mac asks for meetings around now at 15:02
- **THEN** it receives today's nearby meetings with "15:00 Quokka sync" marked in progress, and no attendees, notes or other data

### Requirement: Recordings can be linked to a meeting or marked
A recording SHALL be linkable to a chosen meeting when it is registered, and re-linkable or markable with a project afterwards, by its device (its own recordings) and by the owner on the recording's page in the web OS; moving a recording SHALL move its transcript, audio and search item, and re-run processing for the new meeting.

#### Scenario: Re-linked in the web OS
- **WHEN** the owner opens an unscheduled call in the web OS and picks yesterday's "Dealer call" meeting
- **THEN** the recording appears on that meeting's page with its audio, and its summary and actions are redone for that meeting

### Requirement: Recording coverage and cost on Status
Status SHALL show, per week, how many calendar meetings with other attendees have a recording, and the transcription spend of the month split into dictation and calls (on-device transcription counts as free).

#### Scenario: Weekly coverage
- **WHEN** 18 of 20 meetings with attendees this week have a transcript
- **THEN** Status shows "Meetings recorded: 18 of 20 (90%)" and this month's transcription cost
