-- Kid profiles (v2, PR-1): a built-in avatar key as an alternative to an uploaded photo
-- (picture_path wins when both are set), and an admin-controlled order for the picker.
ALTER TABLE profile ADD COLUMN avatar TEXT;
ALTER TABLE profile ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;
UPDATE profile SET sort_order = id;
