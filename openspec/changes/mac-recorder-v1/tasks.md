# Tasks

Each slice ends with its tests passing (`make check` for the server; the macOS CI job for `mac/`),
is committed on branch `change/mac-recorder-v1`, merged to `main` and deployed. Swift code cannot
be compiled in this workspace: every Mac slice is verified by the macOS CI job, and the manual
checks run on the owner's Mac at the end (one checklist, owner preference).

## 1. Server: device dictation, cloud transcription, coverage

- [ ] 1.1 Migration: `dictations.device_id`, `transcription_costs`; `POST /api/devices/dictations` (raw audio, `form` = verbatim/clean/structured; OpenAI `gpt-transcribe` via `kb.dictation`; audio not kept; redacted; budget-aware; in the dictation history; device reads only its own result); dictation transcription cost recorded; verify `test_device_dictation_forms`, `test_device_dictation_over_budget_returns_verbatim`, `test_device_dictation_audio_not_kept`, `test_device_token_still_cannot_read_kb`
- [ ] 1.2 `kb.transcription` providers (OpenAI mini / gpt-transcribe / diarize, Groq via OpenAI-compatible endpoint when `GROQ_API_KEY` is set) with cost; migration `transcription_jobs`; `POST /api/devices/recordings/{id}/transcribe {speakers}` (own recordings, uploaded tracks); routines job replaces segments per track, records cost, re-processes; call provider setting in Settings; month spend includes transcription; verify `test_cloud_transcription_replaces_segments_and_records_cost`, `test_groq_provider_uses_openai_compatible_endpoint`, `test_speakers_use_diarize_for_others_track`, `test_transcribe_refuses_other_devices_and_missing_audio`, `test_month_spend_includes_transcription`
- [ ] 1.3 Meetings for devices and linking: `GET /api/devices/meetings?around=now` (±12 h, minimal fields), `event_id` at registration, `POST /api/devices/recordings/{id}/link` (own recordings) and owner `POST /api/recordings/{id}/link` (meeting or project; re-index, re-process, stale task drafts discarded); meeting picker and project select on the recording page in the web OS; verify `test_device_meetings_minimal_fields`, `test_device_token_reads_only_meetings`, `test_relink_moves_recording_and_reprocesses`, `test_link_refuses_other_devices`, `Meetings.test.tsx` re-link case
- [ ] 1.4 Status: meetings with attendees vs meetings with a recording per week; transcription spend this month by kind (dictation, calls); verify `test_status_recording_coverage_and_spend`, `Status.test.tsx` case

## 2. Mac app skeleton, CI and install

- [ ] 2.1 `mac/` Swift package (app + library targets, universal), menu-bar shell, settings window, Keychain token store, pairing with a one-time code, "not paired" on 401; `.github/workflows/mac.yml` (macos-15: build + test on `mac/**`); verify CI green with `PairingTests`, `KeychainStoreTests` (in-memory backend)
- [ ] 2.2 `mac/install.sh`: release build, sherpa-onnx + Parakeet download with checksums, `.app` bundle with Info.plist usage strings, signing (Apple Development certificate if present, else ad-hoc with a warning), /Applications, Login Item; permissions screen (microphone, system audio, accessibility) with links to System Settings; verify CI runs `install.sh --dry-run` and `PermissionsModelTests`

## 3. Hotkeys and recording

- [ ] 3.1 Changeable hotkeys: Carbon registration, defaults ⌃⌥R / ⌃⌥D / ⇧, recorder fields in Settings, taken combinations refused with the previous kept, hold-vs-toggle for dictation; verify `HotkeyConfigTests` (persist, conflict, immediate re-register with a fake registrar), `HotkeyTimingTests`
- [ ] 3.2 Microphone track (AVAudioEngine, route-change restart) and computer-audio track (Core Audio process tap; ScreenCaptureKit fallback) as 5-minute AAC 16 kHz segments; join on stop; crash recovery; 4-hour limit; menu-bar state and timer; verify `SegmentJoinTests`, `RecoveryTests`, `RecorderStateTests` (fake audio sources)

## 4. Call transcription on the Mac

- [ ] 4.1 sherpa-onnx + Parakeet v3: VAD segmentation, per-track transcription, me/others merge by time, long-segment split; CPU vs Core ML measurement on a bundled sample with the result in Settings; verify `MergeTests`, `ProviderChoiceTests` (fake timings), `SegmentationTests` (fixture VAD output)
- [ ] 4.2 Scheduling: utility QoS, ≤ 3 threads, pause while recording, wait for power on battery unless allowed, dictation queue first; "Call transcription: On this Mac / Cloud" setting; verify `SchedulerTests` (fake power and recording state)
- [ ] 4.3 Live mode (off by default): phrase-by-phrase transcription during recording, floating caption window, transcript complete at stop; verify `LiveAssemblerTests` (streamed fake segments → same transcript as the after-call path)

## 5. Delivery

- [ ] 5.1 Item store and state machine, uploader (register with idempotency key, announce/HEAD/PUT 8 MB chunks, resume on 409/offline, 401 → paused), Cloud mode (register, upload, request `/transcribe`), "Separate speakers" with cost estimate, local audio cleanup 7 days after delivery, menu list with reasons; verify `UploaderTests` (URLProtocol mock incl. 409 and offline), `StateMachineTests`, `CloudModeTests`, `CleanupTests`
- [ ] 5.2 Meeting choice: at recording start the menu offers meetings around now (in progress first, "Automatic" default), sent as `event_id`; recent recordings list with "Change meeting" / "Set project" before and after delivery; verify `MeetingPickerTests` (fake server list, offline → Automatic only), `RelinkTests`

## 6. Dictation

- [ ] 6.1 Dictation hotkey flow: record, send to `/api/devices/dictations` with the chosen form (default as said or cleaned; ⇧ structured), insertion by pasteboard + ⌘V with clipboard restore, clipboard fallback, offline local Parakeet as said with a notification; verify `DictationFlowTests` (fake server, fake paster, offline path)

## 7. Imports

- [ ] 7.1 Drag & drop and "Import…" (m4a, mp3, wav, caf, ogg), kind choice, watched folder (bookmark + FSEvents, imported once, Full Disk Access hint for Voice Memos); verify `ImportDedupTests`, `WatchedFolderTests` (temporary folder)

## 8. Docs and acceptance

- [ ] 8.1 ADR 0014 amendment (Mac first, iPhone later; calls on-device with Parakeet, dictation via OpenAI, cloud fallback), `docs/architecture.md`, `docs/external/README.md` (Mac permissions, certificate, macOS CI minutes, optional `GROQ_API_KEY`), STATUS; verify `openspec validate --all`
- [ ] 8.2 Owner acceptance on the Mac: install, pair, change a hotkey; record a Zoom, a Telegram and a Meet call (both tracks; pick the meeting at the start once, re-link one afterwards, mark one unscheduled call with a project; check both audio tracks play on the meeting page; note the measured speed and CPU/GPU choice); compare 2–3 real calls Parakeet vs OpenAI gpt-transcribe and decide the call engine (Mac / OpenAI / Groq); dictate into Telegram and mail (uk, ru, mixed; as said / cleaned / structured; once offline); import an iPhone call recording and a watched voice memo; go offline and back; Live mode once; record results and costs in STATUS

## Workflow follow-up

- After 4 weeks, check the success metric on Status (≥ 90% of meetings recorded, ≤ $10/month); the human archives the change.
