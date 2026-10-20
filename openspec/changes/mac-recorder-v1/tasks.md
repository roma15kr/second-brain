# Tasks

Each slice ends with its tests passing (`make check` for the server; the macOS CI job for `mac/`),
is committed on branch `change/mac-recorder-v1`, merged to `main` and deployed. Swift code cannot
be compiled in this workspace: every Mac slice is verified by the macOS CI job, and the manual
checks run on the owner's Mac at the end (one checklist, owner preference).

## 1. Server: device dictation, cloud transcription, coverage

- [ ] 1.1 Migration: `dictations.device_id`; `POST /api/devices/dictations {text, form}` (verbatim / clean / structured, redacted, budget-aware, in the dictation history; device reads only its own result); verify `test_device_dictation_forms`, `test_device_dictation_over_budget_returns_verbatim`, `test_device_token_still_cannot_read_kb`
- [ ] 1.2 Migration: `transcription_jobs`, `transcription_costs`; `POST /api/devices/recordings/{id}/transcribe` (own recordings, uploaded others track, ≤ 25 MB) and the routines job (diarized transcription, segments replaced for the others track, cost recorded, re-processed); month spend includes transcription; verify `test_cloud_transcription_replaces_others_segments_and_records_cost`, `test_transcribe_refuses_other_devices_and_missing_audio`, `test_month_spend_includes_transcription`
- [ ] 1.3 Status: meetings with attendees vs meetings with a recording per week, transcription spend this month; verify `test_status_recording_coverage`, `Status.test.tsx` case

## 2. Mac app skeleton, CI and install

- [ ] 2.1 `mac/` Swift package (app + library targets), menu-bar shell, settings window, Keychain token store, pairing with a one-time code, "not paired" state on 401; `.github/workflows/mac.yml` (macos-15: build + test on `mac/**` changes); verify CI green with `PairingTests`, `KeychainStoreTests` (in-memory backend)
- [ ] 2.2 `mac/install.sh`: release build, `.app` bundle with Info.plist usage strings, signing (Apple Development certificate if present, else ad-hoc with a warning), copy to /Applications, Login Item; permissions screen (microphone, system audio, accessibility) with links to System Settings; verify CI builds the bundle (`install.sh --dry-run`) and `PermissionsModelTests`

## 3. Recording

- [ ] 3.1 Microphone track (AVAudioEngine, route-change restart) and computer-audio track (Core Audio process tap; ScreenCaptureKit fallback) written as 5-minute AAC segments; join on stop; crash recovery on start; 4-hour limit; verify `SegmentJoinTests`, `RecoveryTests`, `RecorderStateTests` (fake audio sources)
- [ ] 3.2 Global hotkeys (Carbon), record toggle ⌃⌥R with menu-bar state and timer, configurable in settings; verify `HotkeyTimingTests` (hold vs toggle) and `MenuStateTests`

## 4. Transcription on the Mac

- [ ] 4.1 WhisperKit integration (model download with progress, warm/unload policy), VAD, per-track transcription, me/others merge by time, low-confidence segment filter, priority queue (dictation first); verify `MergeTests`, `QueuePriorityTests`, `HallucinationFilterTests` (fixtures of WhisperKit results)

## 5. Delivery

- [ ] 5.1 Item store and state machine, uploader (register recording with idempotency key, announce/HEAD/PUT 8 MB chunks, resume on 409/offline, revoked → paused), local audio cleanup 7 days after delivery, menu list of pending/failed with reasons; verify `UploaderTests` (URLProtocol mock of the device API incl. 409 and offline), `StateMachineTests`, `CleanupTests`
- [ ] 5.2 Cloud transcription choice per recording with cost estimate (server price), calling `/transcribe`; verify `CloudChoiceTests`

## 6. Dictation

- [ ] 6.1 Dictation hotkey ⌃⌥D (hold-to-talk / toggle, ⇧ for structured), local transcription, cleaned/structured via `/api/devices/dictations`, insertion by pasteboard + ⌘V with clipboard restore, clipboard fallback when nothing editable has focus; verify `DictationFlowTests` (fake transcriber, fake server, fake paster)

## 7. Imports

- [ ] 7.1 Drag & drop and "Import…" (m4a, mp3, wav, caf, ogg), kind choice, watched folder (bookmark + FSEvents, imported once, Full Disk Access hint for Voice Memos); verify `ImportDedupTests`, `WatchedFolderTests` (temporary folder)

## 8. Docs and acceptance

- [ ] 8.1 ADR 0014 amendment (Mac first, iPhone later, on-device transcription by default), `docs/architecture.md`, `docs/external/README.md` (Mac permissions, certificates, macOS CI minutes), STATUS; verify `openspec validate --all`
- [ ] 8.2 Owner acceptance on the Mac: install, pair, record a Zoom call, a Telegram call and a Meet call (both tracks, ≤ 15 min transcription for 90 min), dictate into Telegram and mail (uk, ru, mixed; as said / cleaned / structured), import an iPhone call recording and a watched voice memo, go offline and back, cloud transcription for one team meeting; record results and cost in STATUS

## Workflow follow-up

- After 4 weeks, check the success metric on Status (≥ 90% of meetings recorded, ≤ $5/month); the human archives the change.
