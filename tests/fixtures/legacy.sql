BEGIN TRANSACTION;
CREATE TABLE "bot_settings" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "global_caption" TEXT,
    "show_file_captions" INT NOT NULL  DEFAULT 1
);
INSERT INTO "bot_settings" VALUES(1,'global',1);
CREATE TABLE "broadcast_job" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "admin_id" BIGINT NOT NULL,
    "delivery_type" VARCHAR(16) NOT NULL,
    "audience" VARCHAR(128) NOT NULL,
    "status" VARCHAR(16) NOT NULL  DEFAULT 'scheduled',
    "total_count" INT NOT NULL  DEFAULT 0,
    "success_count" INT NOT NULL  DEFAULT 0,
    "failed_count" INT NOT NULL  DEFAULT 0,
    "scheduled_at" TIMESTAMP,
    "started_at" TIMESTAMP,
    "completed_at" TIMESTAMP
);
INSERT INTO "broadcast_job" VALUES(1,42,'copy','all','completed',2,1,1,NULL,'2026-10-04 22:10:07.391601+00:00','2026-10-04 22:10:07.396206+00:00');
CREATE TABLE "channel" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "channel_id" VARCHAR(255) NOT NULL UNIQUE,
    "channel_link" VARCHAR(255) NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "is_active" INT NOT NULL  DEFAULT 1
);
CREATE TABLE "file" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "type" VARCHAR(64) NOT NULL,
    "size" BIGINT NOT NULL,
    "code" VARCHAR(32) NOT NULL UNIQUE,
    "file_id" BIGINT NOT NULL,
    "access_hash" BIGINT NOT NULL,
    "file_reference" BLOB NOT NULL,
    "message_id" BIGINT NOT NULL,
    "count" INT NOT NULL  DEFAULT 0,
    "password" VARCHAR(255),
    "caption" TEXT,
    "album_id" VARCHAR(64),
    "album_order" INT NOT NULL  DEFAULT 0,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "expires_at" TIMESTAMP,
    "max_downloads" INT,
    "owner_id" BIGINT NOT NULL REFERENCES "user" ("userid") ON DELETE CASCADE
);
INSERT INTO "file" VALUES(3,'photo',2048,'protected',8000000000001,-6000000000001,X'00FF726566',55,2,'secret','کپشن',NULL,0,'2026-10-04 22:10:07.411281+00:00',NULL,5,5000000001);
CREATE TABLE "file_access_log" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "viewer_id" BIGINT NOT NULL,
    "file_code" VARCHAR(32) NOT NULL,
    "owner_id" BIGINT NOT NULL,
    "accessed_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO "file_access_log" VALUES(1,42,'album',5000000001,'2026-10-04 22:10:07.380594+00:00');
INSERT INTO "file_access_log" VALUES(2,42,'album',5000000001,'2026-10-04 22:10:07.384190+00:00');
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('user',2);
INSERT INTO "sqlite_sequence" VALUES('channel',1);
INSERT INTO "sqlite_sequence" VALUES('bot_settings',1);
INSERT INTO "sqlite_sequence" VALUES('file',3);
INSERT INTO "sqlite_sequence" VALUES('file_access_log',2);
INSERT INTO "sqlite_sequence" VALUES('broadcast_job',1);
CREATE TABLE "user" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "userid" BIGINT NOT NULL UNIQUE,
    "phone_number" VARCHAR(32),
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "last_activity_at" TIMESTAMP,
    "is_superuser" INT NOT NULL  DEFAULT 0,
    "is_staff" INT NOT NULL  DEFAULT 0
);
INSERT INTO "user" VALUES(1,5000000001,'123','2026-10-04 22:10:07.299480+00:00',NULL,0,0);
INSERT INTO "user" VALUES(2,42,NULL,'2026-10-04 22:10:07.308041+00:00',NULL,0,1);
CREATE INDEX "idx_broadcast_j_admin_i_ce51fb" ON "broadcast_job" ("admin_id");
CREATE INDEX "idx_broadcast_j_status_e1b044" ON "broadcast_job" ("status");
CREATE INDEX "idx_broadcast_j_schedul_7ff03f" ON "broadcast_job" ("scheduled_at");
CREATE INDEX "idx_broadcast_j_status_07eb10" ON "broadcast_job" ("status", "scheduled_at");
CREATE INDEX "idx_broadcast_j_admin_i_d036b9" ON "broadcast_job" ("admin_id", "started_at");
CREATE INDEX "idx_channel_channel_10e7fe" ON "channel" ("channel_id");
CREATE INDEX "idx_channel_channel_a5c932" ON "channel" ("channel_link");
CREATE INDEX "idx_channel_is_acti_d09927" ON "channel" ("is_active");
CREATE INDEX "idx_file_access_viewer__3ed4fa" ON "file_access_log" ("viewer_id");
CREATE INDEX "idx_file_access_file_co_2a9e36" ON "file_access_log" ("file_code");
CREATE INDEX "idx_file_access_owner_i_e29ac3" ON "file_access_log" ("owner_id");
CREATE INDEX "idx_file_access_accesse_ab6ef3" ON "file_access_log" ("accessed_at");
CREATE INDEX "idx_file_access_viewer__cd1a13" ON "file_access_log" ("viewer_id", "accessed_at");
CREATE INDEX "idx_file_access_viewer__0b88b6" ON "file_access_log" ("viewer_id", "file_code");
CREATE INDEX "idx_file_access_file_co_b1e4df" ON "file_access_log" ("file_code", "accessed_at");
CREATE INDEX "idx_user_userid_f0729d" ON "user" ("userid");
CREATE INDEX "idx_user_created_b19d59" ON "user" ("created_at");
CREATE INDEX "idx_user_is_supe_b8a218" ON "user" ("is_superuser");
CREATE INDEX "idx_user_is_staf_93d7e8" ON "user" ("is_staff");
CREATE INDEX "idx_user_is_supe_a6124d" ON "user" ("is_superuser", "is_staff");
CREATE INDEX "idx_file_type_8005ff" ON "file" ("type");
CREATE INDEX "idx_file_code_f85c11" ON "file" ("code");
CREATE INDEX "idx_file_count_583ca6" ON "file" ("count");
CREATE INDEX "idx_file_album_i_224f7a" ON "file" ("album_id");
CREATE INDEX "idx_file_created_3b1e63" ON "file" ("created_at");
CREATE INDEX "idx_file_owner_i_d22aba" ON "file" ("owner_id", "created_at");
CREATE INDEX "idx_file_type_82f7a2" ON "file" ("type", "created_at");
CREATE INDEX "idx_file_album_i_15a14b" ON "file" ("album_id", "album_order");
COMMIT;