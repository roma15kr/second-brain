#!/bin/sh
# Daily pg_dump of the kb database + an automatic restore test into a scratch database.
# Results are written to the backup_checks table (shown by `kb status` / MCP status).
set -u
export PGHOST="${PGHOST:-postgres}" PGUSER="${PGUSER:-kb}" PGPASSWORD="${POSTGRES_PASSWORD:-}"
DB="${KB_DB:-kb}"
export PGDATABASE="$DB"
DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

record() {  # status, dump file, detail
  psql -q -v ON_ERROR_STOP=1 -c "INSERT INTO backup_checks (status, dump_file, detail)
    VALUES ('$1', '$2', \$detail\$$3\$detail\$)" || echo "cannot record backup check"
}

record_audio() {  # status, detail
  psql -q -v ON_ERROR_STOP=1 -c "INSERT INTO backup_checks (kind, status, detail)
    VALUES ('audio', '$1', \$detail\$$2\$detail\$)" || echo "cannot record audio backup check"
}

# Meeting audio: files are immutable, so a copy = new names only; each copy is verified by
# sha256, and copies of audio deleted from the app (12-month retention) are removed too.
backup_audio() {
  SRC="${AUDIO_DIR:-/data/audio}"
  DST="$DIR/audio"
  [ -d "$SRC" ] || return 0
  mkdir -p "$DST"
  LIST=$(mktemp)
  psql -Atc "SELECT path || ' ' || sha256 FROM recording_audio WHERE complete
             AND deleted_at IS NULL" > "$LIST" || { record_audio failed "cannot list audio"; return; }
  COPIED=0; BAD=0
  while read -r path sum; do
    rel="${path#"$SRC"/}"
    [ -f "$DST/$rel" ] && continue
    mkdir -p "$(dirname "$DST/$rel")"
    if cp "$path" "$DST/$rel.tmp" && echo "$sum  $DST/$rel.tmp" | sha256sum -c --status; then
      mv "$DST/$rel.tmp" "$DST/$rel"; COPIED=$((COPIED + 1))
    else
      rm -f "$DST/$rel.tmp"; BAD=$((BAD + 1))
    fi
  done < "$LIST"
  find "$DST" -type f ! -name '*.tmp' | while read -r f; do
    rel="${f#"$DST"/}"
    grep -q "^$SRC/$rel " "$LIST" || { rm -f "$f"; }
  done
  SIZE=$(du -sh "$DST" | cut -f1)
  if [ "$BAD" = 0 ]; then
    record_audio ok "copied $COPIED new files, verified; audio backup $SIZE"
  else
    record_audio checksum_failed "copied $COPIED, $BAD failed verification; audio backup $SIZE"
  fi
  rm -f "$LIST"
}

counts() {  # database → "table=count ..." for the tables that must survive a restore
  psql -d "$1" -Atc "SELECT string_agg(t || '=' || n, ' ' ORDER BY t) FROM (
      SELECT 'raw_records' t, count(*) n FROM raw_records UNION ALL
      SELECT 'messages', count(*) FROM messages UNION ALL
      SELECT 'items', count(*) FROM items UNION ALL
      SELECT 'distillations', count(*) FROM distillations UNION ALL
      SELECT 'identities', count(*) FROM identities) s"
}

until pg_isready -q; do sleep 5; done
while true; do
  STAMP=$(date -u +%Y%m%dT%H%M%SZ)
  FILE="$DIR/kb-$STAMP.dump"
  record running "$FILE" "started"
  BEFORE=$(counts "$DB")
  if pg_dump -Fc -f "$FILE.tmp" && mv "$FILE.tmp" "$FILE"; then
    dropdb --if-exists kb_restore_check && createdb kb_restore_check \
      && psql -q -d kb_restore_check -c "CREATE EXTENSION IF NOT EXISTS vector" \
      && pg_restore -d kb_restore_check --no-owner "$FILE" 2>/tmp/restore.err
    AFTER=$(counts kb_restore_check 2>/dev/null || echo "restore failed")
    dropdb --if-exists kb_restore_check
    SIZE=$(du -h "$FILE" | cut -f1)
    if [ "$BEFORE" = "$AFTER" ]; then
      record ok "$FILE" "size $SIZE; restored counts match: $AFTER"
    else
      record restore_mismatch "$FILE" "size $SIZE; before: $BEFORE; after: $AFTER; $(tail -c 300 /tmp/restore.err)"
    fi
  else
    record dump_failed "$FILE" "pg_dump failed"
  fi
  find "$DIR" -name 'kb-*.dump' -mtime +"$KEEP_DAYS" -delete
  backup_audio
  [ "${BACKUP_ONCE:-0}" = 1 ] && exit 0
  sleep "$INTERVAL"
done
