-- 002_add_last_read_message_id.sql: Track read cursor per member per channel (§6)

ALTER TABLE channel_members ADD COLUMN last_read_message_id INTEGER DEFAULT 0;
