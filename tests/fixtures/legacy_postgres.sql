CREATE TABLE "bot_settings" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "global_caption" TEXT,
    "show_file_captions" BOOL NOT NULL  DEFAULT True
);
COMMENT ON TABLE "bot_settings" IS 'Singleton row storing bot-wide configuration toggles.';
CREATE TABLE "broadcast_job" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "admin_id" BIGINT NOT NULL,
    "delivery_type" VARCHAR(16) NOT NULL,
    "audience" VARCHAR(128) NOT NULL,
    "status" VARCHAR(16) NOT NULL  DEFAULT 'scheduled',
    "total_count" INT NOT NULL  DEFAULT 0,
    "success_count" INT NOT NULL  DEFAULT 0,
    "failed_count" INT NOT NULL  DEFAULT 0,
    "scheduled_at" TIMESTAMPTZ,
    "started_at" TIMESTAMPTZ,
    "completed_at" TIMESTAMPTZ
);
CREATE INDEX "idx_broadcast_j_admin_i_ce51fb" ON "broadcast_job" ("admin_id");
CREATE INDEX "idx_broadcast_j_status_e1b044" ON "broadcast_job" ("status");
CREATE INDEX "idx_broadcast_j_schedul_7ff03f" ON "broadcast_job" ("scheduled_at");
CREATE INDEX "idx_broadcast_j_status_07eb10" ON "broadcast_job" ("status", "scheduled_at");
CREATE INDEX "idx_broadcast_j_admin_i_d036b9" ON "broadcast_job" ("admin_id", "started_at");
COMMENT ON TABLE "broadcast_job" IS 'Stores outcomes of completed and scheduled admin broadcasts.';
CREATE TABLE "channel" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "channel_id" VARCHAR(255) NOT NULL UNIQUE,
    "channel_link" VARCHAR(255) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "is_active" BOOL NOT NULL  DEFAULT True
);
CREATE INDEX "idx_channel_channel_10e7fe" ON "channel" ("channel_id");
CREATE INDEX "idx_channel_channel_a5c932" ON "channel" ("channel_link");
CREATE INDEX "idx_channel_is_acti_d09927" ON "channel" ("is_active");
COMMENT ON TABLE "channel" IS 'Represents a channel that users must join before using the bot.';
CREATE TABLE "file_access_log" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "viewer_id" BIGINT NOT NULL,
    "file_code" VARCHAR(32) NOT NULL,
    "owner_id" BIGINT NOT NULL,
    "accessed_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX "idx_file_access_viewer__3ed4fa" ON "file_access_log" ("viewer_id");
CREATE INDEX "idx_file_access_file_co_2a9e36" ON "file_access_log" ("file_code");
CREATE INDEX "idx_file_access_owner_i_e29ac3" ON "file_access_log" ("owner_id");
CREATE INDEX "idx_file_access_accesse_ab6ef3" ON "file_access_log" ("accessed_at");
CREATE INDEX "idx_file_access_viewer__cd1a13" ON "file_access_log" ("viewer_id", "accessed_at");
CREATE INDEX "idx_file_access_viewer__0b88b6" ON "file_access_log" ("viewer_id", "file_code");
CREATE INDEX "idx_file_access_file_co_b1e4df" ON "file_access_log" ("file_code", "accessed_at");
COMMENT ON TABLE "file_access_log" IS 'A successful view of a shared file link by a Telegram user.';
CREATE TABLE "user" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "userid" BIGINT NOT NULL UNIQUE,
    "phone_number" VARCHAR(32),
    "created_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "last_activity_at" TIMESTAMPTZ,
    "is_superuser" BOOL NOT NULL  DEFAULT False,
    "is_staff" BOOL NOT NULL  DEFAULT False
);
CREATE INDEX "idx_user_userid_f0729d" ON "user" ("userid");
CREATE INDEX "idx_user_created_b19d59" ON "user" ("created_at");
CREATE INDEX "idx_user_is_supe_b8a218" ON "user" ("is_superuser");
CREATE INDEX "idx_user_is_staf_93d7e8" ON "user" ("is_staff");
CREATE INDEX "idx_user_is_supe_a6124d" ON "user" ("is_superuser", "is_staff");
COMMENT ON TABLE "user" IS 'Represents a Telegram user interacting with the bot.';
CREATE TABLE "file" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "type" VARCHAR(64) NOT NULL,
    "size" BIGINT NOT NULL,
    "code" VARCHAR(32) NOT NULL UNIQUE,
    "file_id" BIGINT NOT NULL,
    "access_hash" BIGINT NOT NULL,
    "file_reference" BYTEA NOT NULL,
    "message_id" BIGINT NOT NULL,
    "count" INT NOT NULL  DEFAULT 0,
    "password" VARCHAR(255),
    "caption" TEXT,
    "album_id" VARCHAR(64),
    "album_order" INT NOT NULL  DEFAULT 0,
    "created_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "expires_at" TIMESTAMPTZ,
    "max_downloads" INT,
    "owner_id" BIGINT NOT NULL REFERENCES "user" ("userid") ON DELETE CASCADE
);
CREATE INDEX "idx_file_type_8005ff" ON "file" ("type");
CREATE INDEX "idx_file_code_f85c11" ON "file" ("code");
CREATE INDEX "idx_file_count_583ca6" ON "file" ("count");
CREATE INDEX "idx_file_album_i_224f7a" ON "file" ("album_id");
CREATE INDEX "idx_file_created_3b1e63" ON "file" ("created_at");
CREATE INDEX "idx_file_owner_i_d22aba" ON "file" ("owner_id", "created_at");
CREATE INDEX "idx_file_type_82f7a2" ON "file" ("type", "created_at");
CREATE INDEX "idx_file_album_i_15a14b" ON "file" ("album_id", "album_order");
COMMENT ON TABLE "file" IS 'Represents a stored Telegram media resource.';