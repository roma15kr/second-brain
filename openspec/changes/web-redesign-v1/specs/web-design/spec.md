# Spec Delta

## Purpose

How the web OS looks and is navigated: simple, light and readable on phone and laptop.

## ADDED Requirements

### Requirement: Light, modern look
The web OS SHALL use a light theme by default (light surfaces, one accent colour, rounded cards, generous spacing, readable type at 16 px base) and SHALL switch to a dark variant only when the device asks for dark mode.

#### Scenario: Phone in light mode
- **WHEN** the owner opens the web OS on an iPhone in light mode
- **THEN** pages are light with dark text and blue accents

### Requirement: Five places
The main navigation SHALL have five entries — Today, Moderate, Meetings, Search, Settings — as a bottom tab bar on phones and a sidebar on wider screens; every other page SHALL be reachable from one of them in one tap.

#### Scenario: Finding Library
- **WHEN** the owner wants the Library
- **THEN** it opens from Search in one tap

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
