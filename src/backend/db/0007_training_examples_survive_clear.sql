-- training_examples.message_id had a plain FK with no ON DELETE action, so
-- clearing a conversation (DELETE FROM messages) failed with a foreign key
-- violation the moment any message in it had recorded feedback. Training
-- examples are durable fine-tuning data independent of the live conversation,
-- so losing the message they came from should just null the link, not block
-- the delete.
ALTER TABLE training_examples ALTER COLUMN message_id DROP NOT NULL;
ALTER TABLE training_examples DROP CONSTRAINT IF EXISTS training_examples_message_id_fkey;
ALTER TABLE training_examples
    ADD CONSTRAINT training_examples_message_id_fkey
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL;
