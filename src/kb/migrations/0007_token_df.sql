-- Document frequency per full-text token, for rarity (IDF) scoring. Refreshed periodically
-- from items.tsv (ts_stat); N is stored in sync_state ('_idf', 'stats').
CREATE TABLE token_df (
    token  text PRIMARY KEY,
    df     int  NOT NULL
);
