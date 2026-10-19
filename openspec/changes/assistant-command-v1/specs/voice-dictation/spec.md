# Spec Delta

## Purpose

Lets the owner speak inside the web OS and get back not only a transcript but a cleaned or
structured text (summary, headings, decisions, actions), ready to copy, save or hand to the assistant.

## ADDED Requirements

### Requirement: Record while the app is open
The web OS SHALL record speech from the microphone while the app is open in the foreground, on desktop and phone, for up to 15 minutes per dictation, with a visible timer, pause and stop. Recording SHALL stop when the app goes to the background, and the part recorded so far SHALL be kept.

#### Scenario: Phone locks during dictation
- **WHEN** the owner dictates for 2 minutes and the phone locks
- **THEN** recording stops and the 2 minutes are transcribed

#### Scenario: Limit reached
- **WHEN** a dictation reaches 15 minutes
- **THEN** recording stops with the message "15-minute limit — start another dictation to continue"

### Requirement: Recording survives a lost connection
A recording SHALL be kept on the device until the server confirms the upload, and SHALL be retried when the connection returns.

#### Scenario: Offline
- **WHEN** the owner dictates with no connection
- **THEN** the dictation shows "waiting to upload" and is transcribed automatically once online

### Requirement: Output forms
After transcription the owner SHALL be able to choose among: Verbatim (as spoken), Clean (fillers, repetitions and false starts removed, punctuation fixed, wording kept), Structured (a short summary, then the content under headings with bullet points, then decisions and action items) and As a request (sent to the assistant). Switching forms SHALL not require re-recording.

#### Scenario: Structured note
- **WHEN** the owner dictates a rambling 5-minute account of a meeting and chooses Structured
- **THEN** the result starts with a 2–3 sentence summary, groups the content under headings, and lists decisions and action items with owners and dates when they were said

#### Scenario: Clean keeps the wording
- **WHEN** the owner chooses Clean
- **THEN** fillers and repetitions are gone, but no sentence is reworded, added or dropped

### Requirement: Faithful to what was said
Clean and Structured forms SHALL contain only what was said: no invented facts, names, numbers or dates. Mixed-language speech SHALL be kept in the languages spoken, and Structured SHALL be written in the main language of the dictation.

#### Scenario: Mixed language
- **WHEN** the owner speaks Ukrainian with English product names
- **THEN** the structured text is in Ukrainian and the product names stay in English

#### Scenario: No invented dates
- **WHEN** the owner says "we need to send it soon"
- **THEN** the action item has no due date

### Requirement: Use the result
The owner SHALL be able to copy the result, edit it, save it to the Library as a note with a project mark, or send it to the assistant as a request.

#### Scenario: Save to Library
- **WHEN** the owner saves a structured dictation and marks it quokka
- **THEN** it appears in the Library as a note marked quokka and is searchable

### Requirement: Audio is not kept
The audio of a dictation SHALL be deleted once its transcript is stored; if transcription fails, the audio SHALL be kept for 7 days for retry and then deleted. Transcripts SHALL be redacted before storage.

#### Scenario: After transcription
- **WHEN** a dictation is transcribed
- **THEN** its audio no longer exists on the server and only the redacted transcript and its forms remain

### Requirement: Dictation cost and history
Each dictation SHALL show its transcription and processing cost, count against the monthly AI budget, and be listed in the dictation history for 90 days unless saved to the Library.

#### Scenario: History
- **WHEN** the owner opens the dictation history
- **THEN** recent dictations are listed newest first with date, length, first line and cost
