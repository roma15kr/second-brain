# Spec Delta

## Purpose

How the web OS looks and is navigated: simple, light and readable on phone and laptop.

## ADDED Requirements

### Requirement: Light, modern look
The web OS SHALL use a light theme (light surfaces, one accent colour, rounded cards, generous spacing, readable type at 16 px base) even when the device is in dark mode; a dark variant SHALL be used only when the owner chooses it in Settings.

#### Scenario: Phone in dark mode
- **WHEN** the owner opens the web OS on an iPhone set to dark mode
- **THEN** pages are still light with dark text and blue accents

### Requirement: The assistant is the main action
The assistant and dictation SHALL be one screen: the owner types or speaks; a spoken recording becomes text that can be sent as a request, copied, cleaned, structured or saved to the Library. It SHALL be one tap away everywhere: the centre button of the phone tab bar and the first button of the sidebar.

#### Scenario: Dictate a request on the phone
- **WHEN** the owner taps the centre button, taps the mic and says a question
- **THEN** the text appears and one tap sends it to the assistant

#### Scenario: Dictate a note
- **WHEN** the owner dictates a note and taps "Structured"
- **THEN** the structured text is shown with Copy and Save to Library

### Requirement: Every section is visible
On wide screens the sidebar SHALL list every section in groups (Work, Knowledge, Reports, System); on phones the tab bar SHALL show Today, Moderate, the assistant, Meetings and Menu, and Menu SHALL list every section; no section SHALL be reachable only through search.

#### Scenario: Finding Library on the phone
- **WHEN** the owner wants the Library on the phone
- **THEN** it opens from Menu in one tap

### Requirement: Comfortable on a phone
Tap targets SHALL be at least 44 px high, pages SHALL not scroll sideways at 360 px width, and rows with many actions SHALL show the main actions with the rest under "More".

#### Scenario: Inbox row on the phone
- **WHEN** the owner opens an email row in the Inbox on a phone
- **THEN** "Draft reply" and "Done" are shown and the other actions are under "More"

### Requirement: Today shows actions first
The Today screen SHALL show, above the fold on a phone, the number of items to moderate, the next meetings, and new mentions of the owner and the team, each opening its detail in one tap.

#### Scenario: Morning
- **WHEN** there are 3 drafts and 2 task proposals and a meeting at 10:00
- **THEN** Today shows "5 to moderate" and "10:00 …" without scrolling

### Requirement: Little text per card
Lists SHALL show one title line and at most one line of detail per item; the full text SHALL open on tap.

#### Scenario: Inbox list
- **WHEN** the owner opens a list of 20 emails
- **THEN** each row is at most two lines
