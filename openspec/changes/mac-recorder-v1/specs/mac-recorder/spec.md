# Spec Delta

## Purpose

A Mac menu-bar app that records the owner's calls and meetings from any app, lets the owner dictate
into any app with a hotkey, imports existing recordings, transcribes them on the Mac and delivers
everything to the second brain.

## ADDED Requirements

### Requirement: Record a call or meeting with a hotkey
The app SHALL start and stop a recording with a global hotkey (default ⌃⌥R) or from the menu bar, capturing the owner's microphone and the computer's audio output (any app) as two separate tracks. While recording, the menu-bar icon SHALL show a recording state and the elapsed time.

#### Scenario: Zoom call
- **WHEN** the owner presses ⌃⌥R during a Zoom call and presses it again after 60 minutes
- **THEN** a 60-minute recording exists with a "me" track (microphone) and an "others" track (Zoom's audio)

#### Scenario: Browser meeting
- **WHEN** the owner records a Google Meet call in a browser
- **THEN** the other participants are on the "others" track like with any desktop app

### Requirement: Recording survives interruptions
A recording SHALL be written to disk continuously; if the app quits, the Mac sleeps or the microphone changes, the part recorded so far SHALL be kept and finished as a recording. Recording SHALL stop automatically after 4 hours, with a notification.

#### Scenario: Headphones switched mid-call
- **WHEN** the owner switches from the built-in microphone to AirPods during a recording
- **THEN** recording continues with the new microphone without a gap longer than 2 seconds

#### Scenario: App closed by accident
- **WHEN** the app is quit during a recording
- **THEN** on the next start the recorded part is finished and processed like a normal recording

### Requirement: Dictate into any app
A second global hotkey (default ⌃⌥D; hold to talk, or press to start and again to stop) SHALL record the microphone, transcribe it on the Mac and type the text into the app that has focus. The owner SHALL choose the default output: as said, or cleaned (fillers removed, wording kept); a modifier (default ⇧ with the hotkey) SHALL produce a structured version (summary, points, actions) instead.

#### Scenario: Reply in Telegram
- **WHEN** the owner holds ⌃⌥D in Telegram, speaks two sentences in Ukrainian and releases
- **THEN** the two sentences appear in the message field within 3 seconds after release

#### Scenario: Structured note
- **WHEN** the owner uses ⇧⌃⌥D and speaks for two minutes about a plan
- **THEN** a summary with points and action items is typed into the focused app

#### Scenario: Nowhere to type
- **WHEN** no text field has focus
- **THEN** the text is copied to the clipboard and a notification says so

### Requirement: Import recordings
The owner SHALL be able to import audio files (m4a, mp3, wav, caf, ogg) by dropping them on the app or with "Import…", and to choose a watched folder (for example the Voice Memos folder) from which new recordings are imported automatically, each once.

#### Scenario: iPhone call recording
- **WHEN** the owner drops a call recording exported from the iPhone onto the app
- **THEN** it is transcribed and appears in the second brain as a call with its date

#### Scenario: Watched Voice Memos
- **WHEN** a new voice memo syncs to the Mac's Voice Memos folder that the owner chose to watch
- **THEN** it is imported and transcribed without any action, and never imported twice

### Requirement: Transcription on the Mac by default
Recordings and dictation SHALL be transcribed on the Mac without sending audio to a cloud service, in Ukrainian, Russian and English including mixed speech; silence SHALL be skipped; call transcripts SHALL label each line "me" or "others" by track and keep timestamps. Transcription of a 90-minute call SHALL finish within 15 minutes after the call on the owner's Mac and SHALL not block new recordings or dictation.

#### Scenario: After a call
- **WHEN** a 90-minute two-track call ends
- **THEN** within 15 minutes its transcript with "me" / "others" lines and timestamps is delivered to the second brain

#### Scenario: Dictation during transcription
- **WHEN** a call is being transcribed and the owner dictates
- **THEN** the dictation is handled first and appears within the usual time

### Requirement: Cloud transcription with speakers on request
For a recording, the owner SHALL be able to choose cloud transcription with speaker separation instead (useful when several other people spoke); the app SHALL show the estimated cost before the choice is confirmed.

#### Scenario: Team meeting with five people
- **WHEN** the owner chooses cloud transcription for a 60-minute team meeting
- **THEN** the app shows the estimated cost, and after confirming, the transcript in the second brain separates the speakers of the "others" track

### Requirement: Reliable delivery to the second brain
Each recording SHALL be delivered once: transcript and timing through the device API, both audio tracks as resumable uploads; delivery SHALL continue after sleep, restart or network loss, and the app SHALL show pending, delivered and failed items with the reason. Local audio SHALL be deleted 7 days after the server confirmed it, and kept while delivery is pending.

#### Scenario: Offline on a train
- **WHEN** two calls are recorded without network
- **THEN** both are transcribed, shown as pending, and delivered when the network returns

#### Scenario: Matched to the calendar
- **WHEN** a recorded call overlaps the 15:00 "Quokka sync" calendar event
- **THEN** the transcript and audio are attached to that meeting in the second brain

### Requirement: Pairing and permissions
The app SHALL pair with the second brain using a one-time code from Settings → Recorder apps and keep the device token in the Keychain. On first use it SHALL ask for the macOS permissions it needs (microphone, system audio recording, accessibility for typing), explain each, and show which are missing.

#### Scenario: Revoked device
- **WHEN** the owner revokes the Mac in the web OS
- **THEN** the app shows "not paired" and keeps recordings locally until paired again

### Requirement: Privacy
The app SHALL only record while the owner started it (no automatic recording in v1), never send audio anywhere except the owner's server (and the cloud transcription service when the owner chose it for a recording), and keep the device token only in the Keychain.

#### Scenario: Default behaviour
- **WHEN** the owner joins a call without pressing the hotkey
- **THEN** nothing is recorded
