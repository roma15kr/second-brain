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
A second global hotkey (default ⌃⌥D; hold to talk, or press to start and again to stop) SHALL record the microphone, have it transcribed by OpenAI through the owner's server, and type the text into the app that has focus. Without network the app SHALL transcribe the dictation on the Mac as said and mark it so.

#### Scenario: Reply in Telegram
- **WHEN** the owner holds ⌃⌥D in Telegram, speaks two sentences in Ukrainian and releases
- **THEN** the two sentences appear in the message field within 3 seconds after release

#### Scenario: Offline dictation
- **WHEN** the owner dictates with no network
- **THEN** the text is transcribed on the Mac, typed as said, and a notification says cleaning was not available

#### Scenario: Nowhere to type
- **WHEN** no text field has focus
- **THEN** the text is copied to the clipboard and a notification says so

### Requirement: Dictation output forms
The owner SHALL choose the default dictation output in Settings: as said, or cleaned (fillers removed, wording kept); the structured modifier (default ⇧ with the dictation hotkey) SHALL produce a structured version (summary, points, actions) instead.

#### Scenario: Cleaned by default
- **WHEN** the default output is "cleaned" and the owner dictates "ну, значить, давай зустрінемось завтра"
- **THEN** the typed text is "Давай зустрінемось завтра."

#### Scenario: Structured note
- **WHEN** the owner uses ⇧⌃⌥D and speaks for two minutes about a plan
- **THEN** a summary with points and action items is typed into the focused app

### Requirement: Hotkeys can be changed
The owner SHALL be able to change the recording hotkey, the dictation hotkey and the structured modifier in Settings by pressing the new combination; a combination already used by the system or another app SHALL be refused with a message, and the change SHALL apply immediately.

#### Scenario: New dictation hotkey
- **WHEN** the owner sets dictation to ⌥Space in Settings
- **THEN** ⌥Space starts dictation right away and ⌃⌥D no longer does

#### Scenario: Combination taken
- **WHEN** the owner tries ⌘Space (Spotlight)
- **THEN** the app refuses it and keeps the previous hotkey

### Requirement: Import recordings
The owner SHALL be able to import audio files (m4a, mp3, wav, caf, ogg) by dropping them on the app or with "Import…", and to choose a watched folder (for example the Voice Memos folder) from which new recordings are imported automatically, each once.

#### Scenario: iPhone call recording
- **WHEN** the owner drops a call recording exported from the iPhone onto the app
- **THEN** it is transcribed and appears in the second brain as a call with its date

#### Scenario: Watched Voice Memos
- **WHEN** a new voice memo syncs to the Mac's Voice Memos folder that the owner chose to watch
- **THEN** it is imported and transcribed without any action, and never imported twice

### Requirement: Call transcription on the Mac
Recordings and imports SHALL be transcribed on the Mac with NVIDIA Parakeet v3 by default, without sending audio to a cloud service, in Ukrainian, Russian and English; silence SHALL be skipped; call transcripts SHALL label each line "me" or "others" by track and keep timestamps. The app SHALL measure on first use whether the Mac's CPU or GPU transcribes faster, use the faster one, and show the measured speed in Settings.

#### Scenario: After a call
- **WHEN** a 90-minute two-track call ends and the Mac is on power
- **THEN** its transcript with "me" / "others" lines and timestamps is delivered to the second brain, and the time it took is shown with the recording

#### Scenario: Speed measured
- **WHEN** the app transcribes its first recording
- **THEN** Settings shows the measured speed (for example "7× real time on GPU") and which processor is used

### Requirement: Transcription never gets in the way
Call transcription SHALL run at low priority with a limited number of threads, SHALL not start a full transcription while another recording is running, and on battery SHALL wait for power unless the owner allows battery use in Settings. Dictation SHALL never wait for call transcription.

#### Scenario: Back-to-back calls
- **WHEN** a second call starts while the first is being transcribed
- **THEN** transcription pauses until the second call ends and continues afterwards

#### Scenario: On battery
- **WHEN** a call ends on battery with the default setting
- **THEN** its transcription waits and starts when the Mac is plugged in

### Requirement: Live captions (optional)
In Live mode (off by default), the app SHALL transcribe each track phrase by phrase during the call and show the lines in a small floating window about 1–2 seconds after each phrase; when the call ends, the transcript SHALL already be complete.

#### Scenario: Live mode on
- **WHEN** Live mode is on and the other person finishes a sentence
- **THEN** the sentence appears in the caption window within about 2 seconds, labelled "others"

### Requirement: Cloud transcription of calls when chosen
The owner SHALL be able to switch call transcription from the Mac to the cloud (the server's provider: OpenAI or Groq) in Settings, and to ask for cloud transcription with speaker separation for a single recording; the app SHALL show the estimated cost before a per-recording request is confirmed.

#### Scenario: Local quality not good enough
- **WHEN** the owner sets call transcription to "Cloud"
- **THEN** new recordings are transcribed by the server's provider instead of on the Mac, and the app keeps working the same way

#### Scenario: Team meeting with five people
- **WHEN** the owner asks for speaker separation for a 60-minute team meeting
- **THEN** the app shows the estimated cost, and after confirming, the transcript separates the speakers of the "others" track

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
The app SHALL only record while the owner started it (no automatic recording in v1), never send audio anywhere except the owner's server (which forwards dictation to OpenAI, and calls to the cloud provider only when the owner chose cloud transcription), and keep the device token only in the Keychain.

#### Scenario: Default behaviour
- **WHEN** the owner joins a call without pressing the hotkey
- **THEN** nothing is recorded
