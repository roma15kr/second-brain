-- Mail is linked to confirmed goals by meaning (assistant-actions: email priority; design D18).
ALTER TABLE goals ADD COLUMN embedding vector(1024);
ALTER TABLE goals ADD COLUMN embedded_text text;
