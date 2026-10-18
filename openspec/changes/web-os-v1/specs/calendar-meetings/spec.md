# Spec Delta

## Purpose

Knows the owner's meetings, reminds and prepares for them, and turns meeting notes into a summary,
decisions, the owner's promises and task drafts for the team.

## ADDED Requirements

### Requirement: Calendars are connected read-only and marked
The owner SHALL connect Google calendars by their secret calendar address, and Apple iCloud or other CalDAV calendars with the account email and an app-specific password; each calendar found SHALL be marked personal or a project (or ignored). Events SHALL sync at least every 10 minutes; the system SHALL only read calendars and never change them.

#### Scenario: Apple calendar
- **WHEN** the owner connects iCloud with an app-specific password
- **THEN** the iCloud calendars (e.g. Home, Family) are listed to mark, and marked calendars' events appear on Today

#### Scenario: Work calendar
- **WHEN** the owner adds the RDIM calendar's secret address marked `rdim`
- **THEN** its upcoming events appear on Today and in the Meetings page, scoped `rdim`

### Requirement: Meeting reminders
The system SHALL push a reminder before each meeting the owner has not declined (default 10 minutes, configurable per calendar), with title, time, attendees and a link to the prep page. All-day events SHALL not be reminded; quiet hours SHALL apply.

#### Scenario: Reminder
- **WHEN** a meeting starts at 15:00
- **THEN** at 14:50 a push "15:00 Quokka sync — 3 people, prep ready" arrives and opens the meeting page

### Requirement: Meeting preparation
For each meeting with attendees the system SHALL prepare, by 30 minutes before (or in the morning brief for meetings before 10:00): who the attendees are (linked people), the last conversations with them, open loops both ways, their open ClickUp tasks, related goals, and a suggested agenda of at most 5 points, each point linked to its source.

#### Scenario: Prep for a dealer call
- **WHEN** a call with a dealer is scheduled
- **THEN** the prep lists the last email thread with the dealer, the price list the owner promised, and an agenda point to confirm it

### Requirement: Recorder apps deliver straight to the knowledge base
The owner's own macOS and iOS recorder apps (built in a separate change, ADR 0014) SHALL be paired with the server from the web OS (one-time code or QR, revocable per device) and SHALL deliver call and meeting transcripts (with speakers and timestamps), their notes and voice notes directly, without any manual step. A delivered transcript SHALL be matched to the calendar event that overlaps it (by time, then attendees); otherwise it SHALL be saved as an unscheduled call or meeting.

#### Scenario: Call recorded on the Mac
- **WHEN** the recorder app finishes a Zoom call that matches the 15:00 "Quokka sync" event
- **THEN** within minutes the transcript is attached to that meeting, searchable, and processing starts

#### Scenario: Unscheduled call
- **WHEN** a Telegram call with no calendar event is recorded
- **THEN** it is saved as a call with its date, duration and the people recognised from speakers or the chat

#### Scenario: Revoked device
- **WHEN** the owner revokes a lost iPhone in the web OS
- **THEN** uploads from that device are refused

### Requirement: Manual notes import
For meetings recorded elsewhere, the owner SHALL be able to attach notes or a transcript to a meeting (pasted text, or a .txt, .md, .vtt, .srt or .docx file).

#### Scenario: Attaching a transcript
- **WHEN** the owner uploads a .vtt transcript to yesterday's Quokka sync
- **THEN** the meeting page shows the transcript and processing starts

### Requirement: Meeting summary, decisions and actions
From meeting notes the system SHALL produce a summary, decisions, and action items with owner and due date; the owner's own commitments SHALL become loops, and action items for others SHALL become ClickUp task drafts in the approval queue. Meeting notes SHALL be searchable like other items.

#### Scenario: Team actions
- **WHEN** a transcript says "Олена will update the listings by Friday"
- **THEN** a task draft for Олена due Friday waits in the approval queue, linked to the meeting

### Requirement: Meeting audio is kept for 12 months
The recorder apps SHALL upload the audio of each call or meeting (the owner's voice and the other participants as separate tracks) together with its transcript; the server SHALL store it, verify it arrived complete, and resume interrupted uploads. Audio SHALL be deleted automatically 12 months after the recording, while the transcript, summary and decisions are kept. The owner SHALL be able to delete a recording's audio earlier, or all audio of a scope.

#### Scenario: Upload over a weak connection
- **WHEN** the phone loses the network halfway through uploading a 1-hour recording
- **THEN** the upload continues from where it stopped when the network returns, and the audio is stored once

#### Scenario: Retention
- **WHEN** a recording becomes older than 12 months
- **THEN** its audio is deleted and its transcript, summary and decisions remain searchable

#### Scenario: Deleting a project's audio
- **WHEN** the owner deletes all audio of scope `rdim` after the contract ends
- **THEN** RDIM recordings have no audio left and their transcripts remain

### Requirement: Listening alongside the transcript
The meeting page SHALL play a recording's audio with the transcript beside it: tapping a transcript line SHALL play from that moment, the current line SHALL be highlighted, and the owner SHALL be able to play either track or both and download the audio. Audio SHALL only be available to the signed-in owner and SHALL never be sent to an AI service by the web OS.

#### Scenario: Re-listening to a decision
- **WHEN** the owner taps the line where the commission was agreed
- **THEN** playback starts at that moment of the recording

### Requirement: Audio is backed up and its storage is visible
Audio SHALL be included in the daily backups (copied incrementally, verified by checksum), and Status SHALL show the audio storage used, its growth per month and the next deletions due.

#### Scenario: Storage check
- **WHEN** the owner opens Status
- **THEN** it shows audio storage (e.g. "11.2 GB, +0.9 GB/month") and the last audio backup result

