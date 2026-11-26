from __future__ import annotations

from backend.infrastructure.postgres.migrations import Migration

_UTC_NOW = "to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"


def _json_shape_triggers(
    table_name: str, columns: tuple[tuple[str, str], ...]
) -> tuple[str, ...]:
    col_expr = ", ".join(column_name for column_name, _ in columns)
    conditions = "\n            OR ".join(
        f"(NEW.{column_name} IS NOT NULL AND ("
        f"NOT COALESCE(fitlife_json_valid(NEW.{column_name}), FALSE) "
        f"OR COALESCE(fitlife_json_type(NEW.{column_name}), '') <> '{shape}'))"
        for column_name, shape in columns
    )
    fn_name = f"fn_{table_name}_json_shape"
    fn_stmt = f"""
        CREATE OR REPLACE FUNCTION {fn_name}()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $fn$
        BEGIN
            IF {conditions} THEN
                RAISE EXCEPTION '{table_name} JSON shape mismatch' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $fn$
    """
    return (
        fn_stmt,
        f"""
        CREATE TRIGGER {table_name}_json_shape_insert
        BEFORE INSERT ON {table_name}
        FOR EACH ROW
        EXECUTE FUNCTION {fn_name}()
        """,
        f"""
        CREATE TRIGGER {table_name}_json_shape_update
        BEFORE UPDATE OF {col_expr} ON {table_name}
        FOR EACH ROW
        EXECUTE FUNCTION {fn_name}()
        """,
    )


RECORDS_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="create_records_schema",
        statements=(
            """
            CREATE OR REPLACE FUNCTION fitlife_json_valid(val TEXT)
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            IMMUTABLE
            AS $fn$
            BEGIN
                IF val IS NULL THEN
                    RETURN NULL;
                END IF;
                PERFORM val::json;
                RETURN TRUE;
            EXCEPTION WHEN OTHERS THEN
                RETURN FALSE;
            END;
            $fn$
            """,
            """
            CREATE OR REPLACE FUNCTION fitlife_json_type(val TEXT)
            RETURNS TEXT
            LANGUAGE plpgsql
            IMMUTABLE
            AS $fn$
            BEGIN
                IF val IS NULL THEN
                    RETURN NULL;
                END IF;
                RETURN json_typeof(val::json);
            EXCEPTION WHEN OTHERS THEN
                RETURN NULL;
            END;
            $fn$
            """,
            f"""
            CREATE TABLE data_migrations (
                migration_key TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
                source_backup_path TEXT,
                details_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(details_json)),
                started_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                completed_at TEXT
            )
            """,
            f"""
            CREATE TABLE user_profile_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                age INTEGER NOT NULL CHECK (age >= 18 AND age <= 100),
                height_cm DOUBLE PRECISION NOT NULL CHECK (height_cm >= 120 AND height_cm <= 230),
                weight_kg DOUBLE PRECISION NOT NULL CHECK (weight_kg >= 30 AND weight_kg <= 300),
                energy_parameter TEXT NOT NULL CHECK (energy_parameter IN ('male', 'female', 'neutral')),
                activity_level TEXT NOT NULL CHECK (activity_level IN ('sedentary', 'light', 'moderate', 'high')),
                auto_target_disabled INTEGER NOT NULL DEFAULT 0 CHECK (auto_target_disabled IN (0, 1)),
                safety_conditions_json TEXT NOT NULL DEFAULT '[]' CHECK (fitlife_json_valid(safety_conditions_json)),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE UNIQUE INDEX idx_profile_versions_user_id ON user_profile_versions(user_id, id)",
            f"""
            CREATE TABLE overall_goal_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                goal TEXT NOT NULL CHECK (goal IN ('fat_loss', 'maintenance', 'muscle_gain')),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE UNIQUE INDEX idx_goal_versions_user_id ON overall_goal_versions(user_id, id)",
            f"""
            CREATE TABLE daily_target_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                profile_version_id TEXT,
                overall_goal_version_id TEXT,
                calories DOUBLE PRECISION NOT NULL CHECK (calories >= 800 AND calories <= 6000),
                carbs DOUBLE PRECISION NOT NULL CHECK (carbs >= 0 AND carbs <= 1000),
                protein DOUBLE PRECISION NOT NULL CHECK (protein >= 20 AND protein <= 400),
                fat DOUBLE PRECISION NOT NULL CHECK (fat >= 10 AND fat <= 300),
                source TEXT NOT NULL CHECK (source IN ('deterministic_calculation', 'manual', 'agent_confirmed')),
                formula_version TEXT,
                rationale_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(rationale_json)),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                FOREIGN KEY(user_id, profile_version_id) REFERENCES user_profile_versions(user_id, id) ON DELETE RESTRICT,
                FOREIGN KEY(user_id, overall_goal_version_id) REFERENCES overall_goal_versions(user_id, id) ON DELETE RESTRICT,
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE UNIQUE INDEX idx_target_versions_user_id ON daily_target_versions(user_id, id)",
            "CREATE INDEX idx_target_versions_profile ON daily_target_versions(user_id, profile_version_id)",
            "CREATE INDEX idx_target_versions_goal ON daily_target_versions(user_id, overall_goal_version_id)",
            f"""
            CREATE TABLE daily_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                planned_meal_count INTEGER NOT NULL DEFAULT 3 CHECK (planned_meal_count >= 1 AND planned_meal_count <= 12),
                target_version_id TEXT,
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                updated_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                FOREIGN KEY(user_id, target_version_id) REFERENCES daily_target_versions(user_id, id) ON DELETE RESTRICT,
                UNIQUE(user_id, log_date)
            )
            """,
            "CREATE INDEX idx_daily_logs_target ON daily_logs(user_id, target_version_id)",
            f"""
            CREATE TABLE food_catalog (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT,
                source TEXT NOT NULL CHECK (source IN ('public', 'user_custom', 'agent_estimate', 'legacy_import')),
                source_name TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                dataset_version TEXT,
                name TEXT NOT NULL,
                basis_type TEXT NOT NULL CHECK (basis_type IN ('per_100g', 'per_100ml', 'per_serving')),
                basis_amount DOUBLE PRECISION NOT NULL CHECK (basis_amount > 0),
                unit TEXT NOT NULL,
                calories DOUBLE PRECISION NOT NULL CHECK (calories >= 0),
                carbs DOUBLE PRECISION NOT NULL CHECK (carbs >= 0),
                protein DOUBLE PRECISION NOT NULL CHECK (protein >= 0),
                fat DOUBLE PRECISION NOT NULL CHECK (fat >= 0),
                license TEXT,
                attribution TEXT,
                provenance_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(provenance_json)),
                content_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                updated_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                CHECK (
                    (source = 'public' AND owner_user_id IS NULL)
                    OR (
                        source IN ('user_custom', 'agent_estimate', 'legacy_import')
                        AND owner_user_id IS NOT NULL
                    )
                )
            )
            """,
            "CREATE UNIQUE INDEX idx_food_public_source ON food_catalog(source_name, source_record_id) WHERE owner_user_id IS NULL",
            "CREATE UNIQUE INDEX idx_food_private_source ON food_catalog(owner_user_id, source_name, source_record_id) WHERE owner_user_id IS NOT NULL",
            "CREATE INDEX idx_food_owner_name ON food_catalog(owner_user_id, name)",
            f"""
            CREATE TABLE exercise_catalog (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT,
                source TEXT NOT NULL CHECK (source IN ('public', 'user_custom', 'agent_estimate', 'legacy_import')),
                source_name TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                dataset_version TEXT,
                name TEXT NOT NULL,
                exercise_type TEXT NOT NULL CHECK (exercise_type IN ('strength', 'cardio')),
                primary_muscle TEXT NOT NULL,
                secondary_muscles_json TEXT NOT NULL DEFAULT '[]' CHECK (fitlife_json_valid(secondary_muscles_json)),
                met DOUBLE PRECISION CHECK (met IS NULL OR met > 0),
                license TEXT,
                attribution TEXT,
                provenance_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(provenance_json)),
                content_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                updated_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                CHECK (
                    (source = 'public' AND owner_user_id IS NULL)
                    OR (
                        source IN ('user_custom', 'agent_estimate', 'legacy_import')
                        AND owner_user_id IS NOT NULL
                    )
                )
            )
            """,
            "CREATE UNIQUE INDEX idx_exercise_public_source ON exercise_catalog(source_name, source_record_id) WHERE owner_user_id IS NULL",
            "CREATE UNIQUE INDEX idx_exercise_private_source ON exercise_catalog(owner_user_id, source_name, source_record_id) WHERE owner_user_id IS NOT NULL",
            "CREATE INDEX idx_exercise_owner_name ON exercise_catalog(owner_user_id, name)",
            """
            CREATE TABLE catalog_aliases (
                id TEXT PRIMARY KEY,
                food_id TEXT,
                exercise_id TEXT,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                alias_kind TEXT NOT NULL CHECK (alias_kind IN ('zh', 'en', 'alias', 'pinyin')),
                FOREIGN KEY(food_id) REFERENCES food_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(exercise_id) REFERENCES exercise_catalog(id) ON DELETE CASCADE,
                CHECK ((food_id IS NOT NULL) <> (exercise_id IS NOT NULL))
            )
            """,
            "CREATE INDEX idx_catalog_alias_food ON catalog_aliases(food_id)",
            "CREATE INDEX idx_catalog_alias_exercise ON catalog_aliases(exercise_id)",
            "CREATE INDEX idx_catalog_alias_normalized ON catalog_aliases(normalized_alias)",
            f"""
            CREATE TABLE catalog_favorites (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                food_id TEXT,
                exercise_id TEXT,
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                FOREIGN KEY(food_id) REFERENCES food_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(exercise_id) REFERENCES exercise_catalog(id) ON DELETE CASCADE,
                CHECK ((food_id IS NOT NULL) <> (exercise_id IS NOT NULL))
            )
            """,
            "CREATE UNIQUE INDEX idx_catalog_favorites_user_food ON catalog_favorites(user_id, food_id) WHERE food_id IS NOT NULL",
            "CREATE UNIQUE INDEX idx_catalog_favorites_user_exercise ON catalog_favorites(user_id, exercise_id) WHERE exercise_id IS NOT NULL",
            "CREATE INDEX idx_catalog_favorites_food ON catalog_favorites(food_id)",
            "CREATE INDEX idx_catalog_favorites_exercise ON catalog_favorites(exercise_id)",
            f"""
            CREATE TABLE catalog_usage (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                food_id TEXT,
                exercise_id TEXT,
                use_count INTEGER NOT NULL DEFAULT 1 CHECK (use_count >= 1),
                last_used_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                FOREIGN KEY(food_id) REFERENCES food_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(exercise_id) REFERENCES exercise_catalog(id) ON DELETE CASCADE,
                CHECK ((food_id IS NOT NULL) <> (exercise_id IS NOT NULL))
            )
            """,
            "CREATE UNIQUE INDEX idx_catalog_usage_user_food ON catalog_usage(user_id, food_id) WHERE food_id IS NOT NULL",
            "CREATE UNIQUE INDEX idx_catalog_usage_user_exercise ON catalog_usage(user_id, exercise_id) WHERE exercise_id IS NOT NULL",
            "CREATE INDEX idx_catalog_usage_food ON catalog_usage(food_id)",
            "CREATE INDEX idx_catalog_usage_exercise ON catalog_usage(exercise_id)",
            "CREATE INDEX idx_catalog_usage_recent ON catalog_usage(user_id, last_used_at DESC)",
            f"""
            CREATE TABLE record_drafts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('meal', 'workout', 'smart_entry', 'daily_target')),
                schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
                payload_json TEXT NOT NULL CHECK (fitlife_json_valid(payload_json)),
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                agent_status TEXT NOT NULL DEFAULT 'not_requested' CHECK (agent_status IN ('not_requested', 'running', 'completed', 'failed')),
                agent_prompt_version TEXT,
                agent_model TEXT,
                agent_metadata_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(agent_metadata_json)),
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                updated_at TEXT NOT NULL DEFAULT ({_UTC_NOW})
            )
            """,
            "CREATE INDEX idx_record_drafts_user_expiry ON record_drafts(user_id, expires_at)",
            f"""
            CREATE TABLE meals (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                name TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                position INTEGER NOT NULL CHECK (position >= 1),
                entry_method TEXT NOT NULL CHECK (entry_method IN ('form', 'smart_entry', 'csv', 'legacy')),
                legacy_source_id TEXT,
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                updated_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                UNIQUE(user_id, log_date, position)
            )
            """,
            f"""
            CREATE TABLE meal_items (
                id TEXT PRIMARY KEY,
                meal_id TEXT NOT NULL,
                catalog_food_id TEXT,
                food_name TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL CHECK (amount > 0),
                unit TEXT NOT NULL,
                basis_type TEXT NOT NULL CHECK (basis_type IN ('per_100g', 'per_100ml', 'per_serving')),
                calories DOUBLE PRECISION NOT NULL CHECK (calories >= 0),
                carbs DOUBLE PRECISION NOT NULL CHECK (carbs >= 0),
                protein DOUBLE PRECISION NOT NULL CHECK (protein >= 0),
                fat DOUBLE PRECISION NOT NULL CHECK (fat >= 0),
                source TEXT NOT NULL CHECK (source IN ('public', 'user_custom', 'agent_estimate', 'legacy_import')),
                is_estimate INTEGER NOT NULL DEFAULT 0 CHECK (is_estimate IN (0, 1)),
                uncertainty_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(uncertainty_json)),
                assumptions_json TEXT NOT NULL DEFAULT '[]' CHECK (fitlife_json_valid(assumptions_json)),
                provenance_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(provenance_json)),
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                FOREIGN KEY(meal_id) REFERENCES meals(id) ON DELETE CASCADE,
                FOREIGN KEY(catalog_food_id) REFERENCES food_catalog(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX idx_meal_items_meal ON meal_items(meal_id)",
            "CREATE INDEX idx_meal_items_catalog ON meal_items(catalog_food_id)",
            f"""
            CREATE TABLE training_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                title TEXT NOT NULL,
                started_at TEXT,
                duration_min DOUBLE PRECISION CHECK (duration_min IS NULL OR duration_min > 0),
                intensity TEXT CHECK (intensity IS NULL OR intensity IN ('low', 'medium', 'high')),
                entry_method TEXT NOT NULL CHECK (entry_method IN ('form', 'smart_entry', 'csv', 'legacy')),
                estimated_calories DOUBLE PRECISION CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(estimate_json)),
                legacy_source_id TEXT,
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                updated_at TEXT NOT NULL DEFAULT ({_UTC_NOW})
            )
            """,
            "CREATE INDEX idx_training_sessions_user_date ON training_sessions(user_id, log_date)",
            """
            CREATE TABLE strength_exercises (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                catalog_exercise_id TEXT,
                exercise_name TEXT NOT NULL,
                primary_muscle TEXT NOT NULL,
                secondary_muscles_json TEXT NOT NULL DEFAULT '[]' CHECK (fitlife_json_valid(secondary_muscles_json)),
                estimated_calories DOUBLE PRECISION CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{}' CHECK (fitlife_json_valid(estimate_json)),
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (fitlife_json_valid(provenance_json)),
                position INTEGER NOT NULL CHECK (position >= 1),
                FOREIGN KEY(session_id) REFERENCES training_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(catalog_exercise_id) REFERENCES exercise_catalog(id) ON DELETE SET NULL,
                UNIQUE(session_id, position)
            )
            """,
            "CREATE INDEX idx_strength_exercises_catalog ON strength_exercises(catalog_exercise_id)",
            """
            CREATE TABLE strength_sets (
                id TEXT PRIMARY KEY,
                strength_exercise_id TEXT NOT NULL,
                set_number INTEGER NOT NULL CHECK (set_number >= 1),
                reps INTEGER NOT NULL CHECK (reps >= 1),
                load_kg DOUBLE PRECISION CHECK (load_kg IS NULL OR load_kg >= 0),
                bodyweight INTEGER NOT NULL DEFAULT 0 CHECK (bodyweight IN (0, 1)),
                FOREIGN KEY(strength_exercise_id) REFERENCES strength_exercises(id) ON DELETE CASCADE,
                UNIQUE(strength_exercise_id, set_number)
            )
            """,
            """
            CREATE TABLE cardio_items (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                catalog_exercise_id TEXT,
                activity_name TEXT NOT NULL,
                duration_min DOUBLE PRECISION NOT NULL CHECK (duration_min > 0),
                device_calories DOUBLE PRECISION CHECK (device_calories IS NULL OR device_calories >= 0),
                met DOUBLE PRECISION CHECK (met IS NULL OR met > 0),
                estimated_calories DOUBLE PRECISION CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{}' CHECK (fitlife_json_valid(estimate_json)),
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (fitlife_json_valid(provenance_json)),
                position INTEGER NOT NULL CHECK (position >= 1),
                FOREIGN KEY(session_id) REFERENCES training_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(catalog_exercise_id) REFERENCES exercise_catalog(id) ON DELETE SET NULL,
                UNIQUE(session_id, position)
            )
            """,
            "CREATE INDEX idx_cardio_items_catalog ON cardio_items(catalog_exercise_id)",
            f"""
            CREATE TABLE idempotency_keys (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                response_json TEXT NOT NULL CHECK (fitlife_json_valid(response_json)),
                created_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                UNIQUE(user_id, operation, idempotency_key)
            )
            """,
            f"""
            CREATE TABLE catalog_imports (
                source_name TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                checksum TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
                imported_count INTEGER NOT NULL DEFAULT 0 CHECK (imported_count >= 0),
                rejected_count INTEGER NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
                details_json TEXT NOT NULL DEFAULT '{{}}' CHECK (fitlife_json_valid(details_json)),
                started_at TEXT NOT NULL DEFAULT ({_UTC_NOW}),
                completed_at TEXT,
                PRIMARY KEY(source_name, dataset_version)
            )
            """,
            """
            CREATE TABLE catalog_search (
                catalog_kind TEXT NOT NULL,
                catalog_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                aliases TEXT NOT NULL DEFAULT '',
                pinyin TEXT NOT NULL DEFAULT '',
                source_tokens TEXT NOT NULL DEFAULT '',
                search_tsv TSVECTOR GENERATED ALWAYS AS (
                    to_tsvector(
                        'simple',
                        coalesce(name, '') || ' ' || coalesce(aliases, '') || ' ' || coalesce(pinyin, '') || ' ' || coalesce(source_tokens, '')
                    )
                ) STORED,
                PRIMARY KEY (catalog_kind, catalog_id)
            )
            """,
            "CREATE INDEX idx_catalog_search_tsv ON catalog_search USING GIN (search_tsv)",
        ),
    ),
    Migration(
        version=2,
        name="enforce_records_schema_invariants",
        statements=(
            """
            CREATE TABLE records_v2_migration_guard (
                violations INTEGER NOT NULL CHECK (violations = 0)
            )
            """,
            """
            INSERT INTO records_v2_migration_guard (violations)
            SELECT COALESCE(SUM(violations), 0)::INTEGER
            FROM (
                SELECT COUNT(*) AS violations
                FROM catalog_favorites AS favorite
                WHERE favorite.food_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM food_catalog AS food
                    WHERE food.id = favorite.food_id
                      AND (food.owner_user_id IS NULL OR food.owner_user_id = favorite.user_id)
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM catalog_favorites AS favorite
                WHERE favorite.exercise_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM exercise_catalog AS exercise
                    WHERE exercise.id = favorite.exercise_id
                      AND (exercise.owner_user_id IS NULL OR exercise.owner_user_id = favorite.user_id)
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM catalog_usage AS usage
                WHERE usage.food_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM food_catalog AS food
                    WHERE food.id = usage.food_id
                      AND (food.owner_user_id IS NULL OR food.owner_user_id = usage.user_id)
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM catalog_usage AS usage
                WHERE usage.exercise_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM exercise_catalog AS exercise
                    WHERE exercise.id = usage.exercise_id
                      AND (exercise.owner_user_id IS NULL OR exercise.owner_user_id = usage.user_id)
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM meal_items AS item
                WHERE item.catalog_food_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM meals AS meal
                    JOIN food_catalog AS food ON food.id = item.catalog_food_id
                    WHERE meal.id = item.meal_id
                      AND (food.owner_user_id IS NULL OR food.owner_user_id = meal.user_id)
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM strength_exercises AS item
                WHERE item.catalog_exercise_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM training_sessions AS session
                    JOIN exercise_catalog AS exercise ON exercise.id = item.catalog_exercise_id
                    WHERE session.id = item.session_id
                      AND exercise.exercise_type = 'strength'
                      AND (exercise.owner_user_id IS NULL OR exercise.owner_user_id = session.user_id)
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM cardio_items AS item
                WHERE item.catalog_exercise_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM training_sessions AS session
                    JOIN exercise_catalog AS exercise ON exercise.id = item.catalog_exercise_id
                    WHERE session.id = item.session_id
                      AND exercise.exercise_type = 'cardio'
                      AND (exercise.owner_user_id IS NULL OR exercise.owner_user_id = session.user_id)
                  )
                UNION ALL
                SELECT COUNT(*) FROM data_migrations
                WHERE COALESCE(fitlife_json_type(details_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM user_profile_versions
                WHERE COALESCE(fitlife_json_type(safety_conditions_json), '') <> 'array'
                UNION ALL
                SELECT COUNT(*) FROM daily_target_versions
                WHERE COALESCE(fitlife_json_type(rationale_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM food_catalog
                WHERE COALESCE(fitlife_json_type(provenance_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM exercise_catalog
                WHERE COALESCE(fitlife_json_type(secondary_muscles_json), '') <> 'array'
                UNION ALL
                SELECT COUNT(*) FROM exercise_catalog
                WHERE COALESCE(fitlife_json_type(provenance_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM record_drafts
                WHERE COALESCE(fitlife_json_type(payload_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM record_drafts
                WHERE COALESCE(fitlife_json_type(agent_metadata_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM meal_items
                WHERE COALESCE(fitlife_json_type(uncertainty_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM meal_items
                WHERE COALESCE(fitlife_json_type(assumptions_json), '') <> 'array'
                UNION ALL
                SELECT COUNT(*) FROM meal_items
                WHERE COALESCE(fitlife_json_type(provenance_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM training_sessions
                WHERE COALESCE(fitlife_json_type(estimate_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM strength_exercises
                WHERE COALESCE(fitlife_json_type(secondary_muscles_json), '') <> 'array'
                UNION ALL
                SELECT COUNT(*) FROM strength_exercises
                WHERE COALESCE(fitlife_json_type(estimate_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM strength_exercises
                WHERE COALESCE(fitlife_json_type(provenance_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM cardio_items
                WHERE COALESCE(fitlife_json_type(estimate_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM cardio_items
                WHERE COALESCE(fitlife_json_type(provenance_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM idempotency_keys
                WHERE COALESCE(fitlife_json_type(response_json), '') <> 'object'
                UNION ALL
                SELECT COUNT(*) FROM catalog_imports
                WHERE COALESCE(fitlife_json_type(details_json), '') <> 'object'
            ) AS checks
            """,
            """
            CREATE OR REPLACE FUNCTION fn_food_catalog_partition_immutable()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
                IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
                   OR NEW.source IS DISTINCT FROM OLD.source THEN
                    RAISE EXCEPTION 'food catalog ownership is immutable' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END;
            $fn$
            """,
            """
            CREATE TRIGGER food_catalog_partition_immutable
            BEFORE UPDATE OF owner_user_id, source ON food_catalog
            FOR EACH ROW
            EXECUTE FUNCTION fn_food_catalog_partition_immutable()
            """,
            """
            CREATE OR REPLACE FUNCTION fn_exercise_catalog_partition_type_immutable()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
                IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
                   OR NEW.source IS DISTINCT FROM OLD.source
                   OR NEW.exercise_type IS DISTINCT FROM OLD.exercise_type THEN
                    RAISE EXCEPTION 'exercise catalog ownership and type are immutable' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END;
            $fn$
            """,
            """
            CREATE TRIGGER exercise_catalog_partition_type_immutable
            BEFORE UPDATE OF owner_user_id, source, exercise_type ON exercise_catalog
            FOR EACH ROW
            EXECUTE FUNCTION fn_exercise_catalog_partition_type_immutable()
            """,
            """
            CREATE OR REPLACE FUNCTION fn_catalog_visible_check()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
                IF (
                    NEW.food_id IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM food_catalog
                        WHERE id = NEW.food_id
                          AND (owner_user_id IS NULL OR owner_user_id = NEW.user_id)
                    )
                ) OR (
                    NEW.exercise_id IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM exercise_catalog
                        WHERE id = NEW.exercise_id
                          AND (owner_user_id IS NULL OR owner_user_id = NEW.user_id)
                    )
                ) THEN
                    IF TG_TABLE_NAME = 'catalog_favorites' THEN
                        RAISE EXCEPTION 'catalog favorite is not visible to user' USING ERRCODE = 'check_violation';
                    ELSE
                        RAISE EXCEPTION 'catalog usage is not visible to user' USING ERRCODE = 'check_violation';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $fn$
            """,
            """
            CREATE TRIGGER catalog_favorites_visible_insert
            BEFORE INSERT ON catalog_favorites
            FOR EACH ROW
            EXECUTE FUNCTION fn_catalog_visible_check()
            """,
            """
            CREATE TRIGGER catalog_favorites_visible_update
            BEFORE UPDATE OF user_id, food_id, exercise_id ON catalog_favorites
            FOR EACH ROW
            EXECUTE FUNCTION fn_catalog_visible_check()
            """,
            """
            CREATE TRIGGER catalog_usage_visible_insert
            BEFORE INSERT ON catalog_usage
            FOR EACH ROW
            EXECUTE FUNCTION fn_catalog_visible_check()
            """,
            """
            CREATE TRIGGER catalog_usage_visible_update
            BEFORE UPDATE OF user_id, food_id, exercise_id ON catalog_usage
            FOR EACH ROW
            EXECUTE FUNCTION fn_catalog_visible_check()
            """,
            """
            CREATE OR REPLACE FUNCTION fn_meals_owner_immutable()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
                IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
                    RAISE EXCEPTION 'meal owner is immutable' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END;
            $fn$
            """,
            """
            CREATE TRIGGER meals_owner_immutable
            BEFORE UPDATE OF user_id ON meals
            FOR EACH ROW
            EXECUTE FUNCTION fn_meals_owner_immutable()
            """,
            """
            CREATE OR REPLACE FUNCTION fn_meal_items_visible_check()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
                IF NEW.catalog_food_id IS NOT NULL
                   AND NOT EXISTS (
                    SELECT 1
                    FROM meals AS meal
                    JOIN food_catalog AS food ON food.id = NEW.catalog_food_id
                    WHERE meal.id = NEW.meal_id
                      AND (food.owner_user_id IS NULL OR food.owner_user_id = meal.user_id)
                   ) THEN
                    RAISE EXCEPTION 'catalog food is not visible to meal owner' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END;
            $fn$
            """,
            """
            CREATE TRIGGER meal_items_visible_insert
            BEFORE INSERT ON meal_items
            FOR EACH ROW
            EXECUTE FUNCTION fn_meal_items_visible_check()
            """,
            """
            CREATE TRIGGER meal_items_visible_update
            BEFORE UPDATE OF meal_id, catalog_food_id ON meal_items
            FOR EACH ROW
            EXECUTE FUNCTION fn_meal_items_visible_check()
            """,
            """
            CREATE OR REPLACE FUNCTION fn_training_sessions_owner_immutable()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
                IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
                    RAISE EXCEPTION 'training session owner is immutable' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END;
            $fn$
            """,
            """
            CREATE TRIGGER training_sessions_owner_immutable
            BEFORE UPDATE OF user_id ON training_sessions
            FOR EACH ROW
            EXECUTE FUNCTION fn_training_sessions_owner_immutable()
            """,
            """
            CREATE OR REPLACE FUNCTION fn_strength_exercises_catalog_check()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
                IF NEW.catalog_exercise_id IS NOT NULL
                   AND NOT EXISTS (
                    SELECT 1
                    FROM training_sessions AS session
                    JOIN exercise_catalog AS exercise ON exercise.id = NEW.catalog_exercise_id
                    WHERE session.id = NEW.session_id
                      AND exercise.exercise_type = 'strength'
                      AND (exercise.owner_user_id IS NULL OR exercise.owner_user_id = session.user_id)
                   ) THEN
                    RAISE EXCEPTION 'catalog exercise must be visible strength exercise' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END;
            $fn$
            """,
            """
            CREATE TRIGGER strength_exercises_catalog_insert
            BEFORE INSERT ON strength_exercises
            FOR EACH ROW
            EXECUTE FUNCTION fn_strength_exercises_catalog_check()
            """,
            """
            CREATE TRIGGER strength_exercises_catalog_update
            BEFORE UPDATE OF session_id, catalog_exercise_id ON strength_exercises
            FOR EACH ROW
            EXECUTE FUNCTION fn_strength_exercises_catalog_check()
            """,
            """
            CREATE OR REPLACE FUNCTION fn_cardio_items_catalog_check()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
                IF NEW.catalog_exercise_id IS NOT NULL
                   AND NOT EXISTS (
                    SELECT 1
                    FROM training_sessions AS session
                    JOIN exercise_catalog AS exercise ON exercise.id = NEW.catalog_exercise_id
                    WHERE session.id = NEW.session_id
                      AND exercise.exercise_type = 'cardio'
                      AND (exercise.owner_user_id IS NULL OR exercise.owner_user_id = session.user_id)
                   ) THEN
                    RAISE EXCEPTION 'catalog exercise must be visible cardio exercise' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END;
            $fn$
            """,
            """
            CREATE TRIGGER cardio_items_catalog_insert
            BEFORE INSERT ON cardio_items
            FOR EACH ROW
            EXECUTE FUNCTION fn_cardio_items_catalog_check()
            """,
            """
            CREATE TRIGGER cardio_items_catalog_update
            BEFORE UPDATE OF session_id, catalog_exercise_id ON cardio_items
            FOR EACH ROW
            EXECUTE FUNCTION fn_cardio_items_catalog_check()
            """,
            *_json_shape_triggers("data_migrations", (("details_json", "object"),)),
            *_json_shape_triggers("user_profile_versions", (("safety_conditions_json", "array"),)),
            *_json_shape_triggers("daily_target_versions", (("rationale_json", "object"),)),
            *_json_shape_triggers("food_catalog", (("provenance_json", "object"),)),
            *_json_shape_triggers(
                "exercise_catalog",
                (("secondary_muscles_json", "array"), ("provenance_json", "object")),
            ),
            *_json_shape_triggers(
                "record_drafts",
                (("payload_json", "object"), ("agent_metadata_json", "object")),
            ),
            *_json_shape_triggers(
                "meal_items",
                (
                    ("uncertainty_json", "object"),
                    ("assumptions_json", "array"),
                    ("provenance_json", "object"),
                ),
            ),
            *_json_shape_triggers("training_sessions", (("estimate_json", "object"),)),
            *_json_shape_triggers(
                "strength_exercises",
                (
                    ("secondary_muscles_json", "array"),
                    ("estimate_json", "object"),
                    ("provenance_json", "object"),
                ),
            ),
            *_json_shape_triggers(
                "cardio_items",
                (("estimate_json", "object"), ("provenance_json", "object")),
            ),
            *_json_shape_triggers("idempotency_keys", (("response_json", "object"),)),
            *_json_shape_triggers("catalog_imports", (("details_json", "object"),)),
            "DROP TABLE records_v2_migration_guard",
        ),
    ),
    Migration(
        version=3,
        name="scope_data_migrations_by_user",
        statements=(
            "ALTER TABLE data_migrations ADD COLUMN user_id TEXT",
            "CREATE INDEX idx_data_migrations_user_status ON data_migrations(user_id, status)",
        ),
    ),
    Migration(
        version=4,
        name="persistent_task_budgets",
        statements=(
            "CREATE TABLE task_budgets (user_id TEXT NOT NULL, task_id TEXT NOT NULL, call_limit INTEGER NOT NULL CHECK(call_limit>=0), token_limit INTEGER NOT NULL CHECK(token_limit>=0), PRIMARY KEY(user_id,task_id))",
            "CREATE TABLE task_budget_operations (user_id TEXT NOT NULL, task_id TEXT NOT NULL, operation_id TEXT NOT NULL, calls INTEGER NOT NULL CHECK(calls>=0), tokens INTEGER NOT NULL CHECK(tokens>=0), actual_calls INTEGER, actual_tokens INTEGER, usage_known INTEGER CHECK(usage_known IN (0,1)), PRIMARY KEY(user_id,task_id,operation_id), FOREIGN KEY(user_id,task_id) REFERENCES task_budgets(user_id,task_id) ON DELETE CASCADE)",
        ),
    ),
    Migration(
        version=5,
        name="entry_interaction_commands",
        statements=(
            """CREATE TABLE entry_interaction_commands (
                draft_id TEXT NOT NULL REFERENCES record_drafts(id) ON DELETE CASCADE,
                idempotency_key TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                response_json TEXT NOT NULL CHECK(fitlife_json_valid(response_json) AND fitlife_json_type(response_json) = 'object' AND octet_length(response_json) <= 294912),
                PRIMARY KEY(draft_id, idempotency_key)
            )""",
        ),
    ),
    Migration(
        version=6,
        name="entry_item_commits",
        statements=(
            """CREATE TABLE entry_item_commits (
                user_id TEXT NOT NULL, draft_id TEXT NOT NULL, item_id TEXT NOT NULL,
                item_revision INTEGER NOT NULL CHECK(item_revision > 0),
                meal_id TEXT NOT NULL, meal_item_id TEXT NOT NULL, record_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(user_id, draft_id, item_id, item_revision)
            )""",
        ),
    ),
    Migration(
        version=7,
        name="coach_conversations",
        statements=(
            """
            CREATE TABLE coach_conversations (
                conversation_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT CHECK (title IS NULL OR length(btrim(title)) > 0),
                status TEXT NOT NULL CHECK (status IN ('active', 'deleted')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                UNIQUE (conversation_id, user_id)
            )
            """,
            """
            CREATE INDEX idx_coach_conversations_owner
            ON coach_conversations (user_id, status, updated_at DESC)
            """,
            """
            CREATE TABLE coach_turns (
                turn_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) > 0),
                request_fingerprint TEXT NOT NULL
                    CHECK (length(btrim(request_fingerprint)) > 0),
                status TEXT NOT NULL CHECK (status IN (
                    'queued', 'running', 'awaiting_user', 'succeeded',
                    'failed', 'cancelled', 'interrupted', 'expired'
                )),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, conversation_id, idempotency_key),
                FOREIGN KEY (conversation_id, user_id)
                    REFERENCES coach_conversations (conversation_id, user_id)
                    ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE coach_messages (
                message_id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'coach')),
                body TEXT NOT NULL CHECK (length(body) > 0),
                review_status TEXT NOT NULL
                    CHECK (review_status IN ('pending', 'approved', 'rejected')),
                created_at TEXT NOT NULL,
                UNIQUE (turn_id, role),
                FOREIGN KEY (turn_id) REFERENCES coach_turns (turn_id) ON DELETE CASCADE,
                FOREIGN KEY (conversation_id, user_id)
                    REFERENCES coach_conversations (conversation_id, user_id)
                    ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX idx_coach_messages_round
            ON coach_messages (user_id, conversation_id, created_at)
            """,
        ),
    ),
    Migration(
        version=8,
        name="coach_turn_execution",
        statements=(
            "ALTER TABLE coach_turns ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE coach_turns ADD COLUMN cancel_requested_at TEXT",
            "ALTER TABLE coach_turns ADD COLUMN started_at TEXT",
            "ALTER TABLE coach_turns ADD COLUMN finished_at TEXT",
            "ALTER TABLE coach_turns ADD COLUMN slot_released_at TEXT",
            "ALTER TABLE coach_turns ADD COLUMN lease_id TEXT",
            "ALTER TABLE coach_turns ADD COLUMN receipt_json TEXT",
            "ALTER TABLE coach_turns ADD COLUMN error_code TEXT",
            "ALTER TABLE coach_conversations ADD COLUMN kind TEXT NOT NULL DEFAULT 'user'",
            """
            CREATE INDEX idx_coach_turns_slot
            ON coach_turns (user_id, status)
            """,
        ),
    ),
    Migration(
        version=9,
        name="plan_adjustment_tasks",
        statements=(
            """
            CREATE TABLE plan_adjustment_sessions (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                version INTEGER NOT NULL CHECK (version >= 1),
                state TEXT NOT NULL CHECK (state IN (
                    'collecting', 'awaiting_scope_permission', 'generating',
                    'repairing', 'awaiting_confirmation', 'awaiting_user_decision',
                    'activated', 'cancelled', 'expired'
                )),
                base_plan_id TEXT NOT NULL,
                base_head_revision INTEGER NOT NULL CHECK (base_head_revision >= 1),
                constraint_digest TEXT NOT NULL,
                constraints_json TEXT NOT NULL
                    CHECK (fitlife_json_valid(constraints_json) AND fitlife_json_type(constraints_json) = 'object'
                           AND octet_length(constraints_json) <= 32768),
                repair_rounds INTEGER NOT NULL DEFAULT 0 CHECK (repair_rounds BETWEEN 0 AND 2),
                active_round_id TEXT,
                candidate_id TEXT,
                candidate_digest TEXT,
                operation_id TEXT,
                expires_at TEXT NOT NULL,
                candidate_expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX idx_plan_adjustment_sessions_owner
            ON plan_adjustment_sessions (user_id, state)
            """,
            """
            CREATE TABLE plan_task_permissions (
                task_id TEXT NOT NULL REFERENCES plan_adjustment_sessions(task_id) ON DELETE CASCADE,
                domain TEXT NOT NULL CHECK (domain IN ('training', 'diet')),
                can_read INTEGER NOT NULL CHECK (can_read IN (0, 1)),
                can_change INTEGER NOT NULL CHECK (can_change IN (0, 1)),
                PRIMARY KEY (task_id, domain),
                CHECK (can_change = 0 OR can_read = 1)
            )
            """,
            """
            CREATE TABLE plan_repair_rounds (
                task_id TEXT NOT NULL REFERENCES plan_adjustment_sessions(task_id) ON DELETE CASCADE,
                round_index INTEGER NOT NULL CHECK (round_index BETWEEN 1 AND 2),
                round_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                failed_domains_json TEXT NOT NULL
                    CHECK (fitlife_json_valid(failed_domains_json) AND fitlife_json_type(failed_domains_json) = 'array'),
                state TEXT NOT NULL CHECK (state IN ('reserved', 'accepted', 'abandoned')),
                created_at TEXT NOT NULL,
                PRIMARY KEY (task_id, round_index),
                UNIQUE (task_id, round_id),
                UNIQUE (task_id, operation_id)
            )
            """,
            """
            CREATE TABLE plan_candidate_submissions (
                task_id TEXT NOT NULL REFERENCES plan_adjustment_sessions(task_id) ON DELETE CASCADE,
                round_index INTEGER NOT NULL CHECK (round_index BETWEEN 0 AND 2),
                candidate_id TEXT NOT NULL,
                bundle_digest TEXT NOT NULL,
                dependency_digest TEXT NOT NULL,
                verdict_json TEXT NOT NULL
                    CHECK (fitlife_json_valid(verdict_json) AND fitlife_json_type(verdict_json) = 'object'
                           AND octet_length(verdict_json) <= 32768),
                passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
                created_at TEXT NOT NULL,
                PRIMARY KEY (task_id, round_index)
            )
            """,
            """
            CREATE TABLE plan_task_receipts (
                user_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                operation_key TEXT NOT NULL,
                task_id TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                response_json TEXT NOT NULL
                    CHECK (fitlife_json_valid(response_json) AND fitlife_json_type(response_json) = 'object'
                           AND octet_length(response_json) <= 32768),
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, scope, operation_key)
            )
            """,
        ),
    ),
    Migration(
        version=10,
        name="plan_candidate_documents",
        statements=(
            "ALTER TABLE plan_candidate_submissions ADD COLUMN candidate_json TEXT "
            "CHECK (candidate_json IS NULL OR (fitlife_json_valid(candidate_json) "
            "AND fitlife_json_type(candidate_json) = 'object' "
            "AND octet_length(candidate_json) <= 65536))",
        ),
    ),
    Migration(
        version=11,
        name="plan_history_and_head",
        statements=(
            """
            CREATE TABLE plans (
                user_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('deterministic', 'agent_adjusted')),
                based_on_plan_id TEXT,
                plan_json TEXT NOT NULL
                    CHECK (fitlife_json_valid(plan_json) AND fitlife_json_type(plan_json) = 'object'
                           AND octet_length(plan_json) <= 262144),
                content_digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, plan_id)
            )
            """,
            """
            CREATE INDEX idx_plans_owner_history
            ON plans (user_id, activated_at DESC, plan_id DESC)
            """,
            """
            CREATE TABLE plan_heads (
                user_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id, plan_id) REFERENCES plans (user_id, plan_id)
            )
            """,
            """
            CREATE TABLE plan_drafts (
                user_id TEXT NOT NULL,
                draft_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('deterministic', 'agent_adjusted')),
                based_on_plan_id TEXT,
                draft_json TEXT NOT NULL
                    CHECK (fitlife_json_valid(draft_json) AND fitlife_json_type(draft_json) = 'object'
                           AND octet_length(draft_json) <= 262144),
                PRIMARY KEY (user_id, draft_id)
            )
            """,
            """
            CREATE TABLE plan_activation_receipts (
                user_id TEXT NOT NULL,
                operation_key TEXT NOT NULL,
                task_id TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                head_revision INTEGER NOT NULL CHECK (head_revision >= 1),
                response_json TEXT NOT NULL
                    CHECK (fitlife_json_valid(response_json) AND fitlife_json_type(response_json) = 'object'
                           AND octet_length(response_json) <= 32768),
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, operation_key)
            )
            """,
            """
            CREATE TABLE plan_import_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                data_dir TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                owner_count INTEGER NOT NULL CHECK (owner_count >= 0),
                plan_count INTEGER NOT NULL CHECK (plan_count >= 0),
                draft_count INTEGER NOT NULL CHECK (draft_count >= 0)
            )
            """,
            "ALTER TABLE plan_adjustment_sessions ADD COLUMN reviewed_digest TEXT",
        ),
    ),
    Migration(
        version=12,
        name="profile_safety_versions",
        statements=(
            """
            CREATE TABLE profile_safety_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                allergies_or_restrictions_json TEXT NOT NULL
                    CHECK (fitlife_json_valid(allergies_or_restrictions_json)
                           AND fitlife_json_type(allergies_or_restrictions_json) = 'array'
                           AND octet_length(allergies_or_restrictions_json) <= 8192),
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX idx_profile_safety_owner
            ON profile_safety_versions (user_id, created_at DESC, id DESC)
            """,
        ),
    ),
    Migration(
        version=13,
        name="body_measurements_and_training_context",
        statements=(
            """
            CREATE TABLE body_measurements (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                measured_date TEXT NOT NULL,
                measured_at TEXT NOT NULL,
                weight_kg DOUBLE PRECISION CHECK (weight_kg IS NULL OR (weight_kg >= 25 AND weight_kg <= 350)),
                body_fat_pct DOUBLE PRECISION CHECK (body_fat_pct IS NULL OR (body_fat_pct >= 2 AND body_fat_pct <= 70)),
                waist_cm DOUBLE PRECISION CHECK (waist_cm IS NULL OR (waist_cm >= 30 AND waist_cm <= 250)),
                chest_cm DOUBLE PRECISION CHECK (chest_cm IS NULL OR (chest_cm >= 40 AND chest_cm <= 250)),
                hip_cm DOUBLE PRECISION CHECK (hip_cm IS NULL OR (hip_cm >= 40 AND hip_cm <= 250)),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (
                    weight_kg IS NOT NULL
                    OR body_fat_pct IS NOT NULL
                    OR waist_cm IS NOT NULL
                    OR chest_cm IS NOT NULL
                    OR hip_cm IS NOT NULL
                )
            )
            """,
            """
            CREATE INDEX idx_body_measurements_user_date
            ON body_measurements (user_id, measured_date DESC, measured_at DESC)
            """,
            """
            CREATE TABLE user_training_context (
                user_id TEXT PRIMARY KEY,
                available_equipment_json TEXT NOT NULL DEFAULT '[]'
                    CHECK (fitlife_json_valid(available_equipment_json) AND fitlife_json_type(available_equipment_json) = 'array'),
                weekly_available_days INTEGER NOT NULL DEFAULT 3
                    CHECK (weekly_available_days BETWEEN 1 AND 7),
                session_duration_min INTEGER NOT NULL DEFAULT 45
                    CHECK (session_duration_min BETWEEN 15 AND 180),
                experience_level TEXT NOT NULL DEFAULT 'beginner'
                    CHECK (experience_level IN ('beginner', 'intermediate', 'advanced')),
                preferred_split TEXT NOT NULL DEFAULT 'auto'
                    CHECK (preferred_split IN ('auto', 'full_body', 'upper_lower', 'push_pull_legs', 'custom')),
                injury_or_limitations_json TEXT NOT NULL DEFAULT '[]'
                    CHECK (fitlife_json_valid(injury_or_limitations_json) AND fitlife_json_type(injury_or_limitations_json) = 'array'),
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """,
        ),
    ),
    Migration(
        version=14,
        name="plan_cycles_and_weekly_automation",
        statements=(
            """
            CREATE TABLE plan_cycles (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                goal_type TEXT NOT NULL
                    CHECK (goal_type IN ('fat_loss', 'muscle_gain', 'maintenance', 'recomposition', 'custom')),
                start_date TEXT NOT NULL,
                duration_weeks INTEGER NOT NULL CHECK (duration_weeks BETWEEN 1 AND 24),
                phases_json TEXT NOT NULL DEFAULT '[]'
                    CHECK (fitlife_json_valid(phases_json) AND fitlife_json_type(phases_json) = 'array'),
                status TEXT NOT NULL
                    CHECK (status IN ('draft', 'active', 'completed', 'archived')),
                source TEXT NOT NULL
                    CHECK (source IN ('manual', 'deterministic', 'agent', 'weekly_auto', 'weekly_auto_deterministic')),
                rationale_json TEXT NOT NULL DEFAULT '{}'
                    CHECK (fitlife_json_valid(rationale_json) AND fitlife_json_type(rationale_json) = 'object'),
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                activated_at TEXT
            )
            """,
            """
            CREATE INDEX idx_plan_cycles_user_status
            ON plan_cycles (user_id, status, updated_at DESC)
            """,
            """
            CREATE TABLE plan_days (
                id TEXT PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                week_index INTEGER NOT NULL CHECK (week_index >= 1),
                day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
                scheduled_date TEXT NOT NULL,
                day_type TEXT NOT NULL CHECK (day_type IN ('training', 'rest', 'cardio')),
                focus TEXT NOT NULL DEFAULT '',
                estimated_duration_min INTEGER
                    CHECK (estimated_duration_min IS NULL OR estimated_duration_min BETWEEN 5 AND 240),
                prescribed_exercises_json TEXT NOT NULL DEFAULT '[]'
                    CHECK (fitlife_json_valid(prescribed_exercises_json) AND fitlife_json_type(prescribed_exercises_json) = 'array'),
                nutrition_override_json TEXT NOT NULL DEFAULT '{}'
                    CHECK (fitlife_json_valid(nutrition_override_json) AND fitlife_json_type(nutrition_override_json) = 'object'),
                status_override TEXT CHECK (status_override IS NULL OR status_override IN ('skipped')),
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (cycle_id) REFERENCES plan_cycles(id) ON DELETE CASCADE,
                UNIQUE (cycle_id, scheduled_date)
            )
            """,
            """
            CREATE INDEX idx_plan_days_user_date
            ON plan_days (user_id, scheduled_date)
            """,
            """
            CREATE TABLE weekly_automation_runs (
                user_id TEXT NOT NULL,
                iso_week TEXT NOT NULL,
                report_week TEXT NOT NULL,
                report_status TEXT NOT NULL
                    CHECK (report_status IN ('generated', 'already_exists', 'failed')),
                draft_cycle_id TEXT,
                draft_status TEXT NOT NULL
                    CHECK (draft_status IN ('generated_agent', 'generated_deterministic', 'already_exists', 'skipped', 'failed')),
                message TEXT NOT NULL DEFAULT '',
                dismissed INTEGER NOT NULL DEFAULT 0 CHECK (dismissed IN (0, 1)),
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, iso_week)
            )
            """,
        ),
    ),
    Migration(
        version=15,
        name="account_state_and_target_weight",
        statements=(
            """
            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                phone TEXT UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                token_version INTEGER NOT NULL DEFAULT 0 CHECK (token_version >= 0),
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE user_preferences (
                user_id TEXT PRIMARY KEY,
                language TEXT NOT NULL CHECK (language IN ('en-US', 'zh-CN')),
                unit_system TEXT NOT NULL CHECK (unit_system IN ('metric', 'imperial')),
                timezone TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE model_connections (
                user_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL DEFAULT 2 CHECK (schema_version = 2),
                revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
                active_json TEXT CHECK (
                    active_json IS NULL OR (fitlife_json_valid(active_json) AND fitlife_json_type(active_json) = 'object')
                ),
                draft_json TEXT CHECK (
                    draft_json IS NULL OR (fitlife_json_valid(draft_json) AND fitlife_json_type(draft_json) = 'object')
                ),
                updated_at TEXT NOT NULL
            )
            """,
            """
            ALTER TABLE overall_goal_versions
            ADD COLUMN target_weight_kg DOUBLE PRECISION
                CHECK (target_weight_kg IS NULL OR (target_weight_kg >= 30 AND target_weight_kg <= 300))
            """,
        ),
    ),
    Migration(
        version=16,
        name="agent_runtime_and_pgvector",
        statements=(
            """
            DO $do$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                    CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
                    CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
                END IF;
            END
            $do$
            """,
            """
            CREATE TABLE agent_runs (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                user_id TEXT,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step TEXT,
                attempt INTEGER NOT NULL,
                public_error_code TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                deadline_at TEXT NOT NULL,
                finished_at TEXT,
                policy_version TEXT NOT NULL,
                policy_snapshot_json TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                input_chars INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                tool_calls INTEGER NOT NULL,
                internal_error_id TEXT,
                failure_stage TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                task_id TEXT,
                task_version INTEGER
            )
            """,
            "CREATE INDEX idx_agent_runs_user_created ON agent_runs (user_id, created_at DESC)",
            "CREATE INDEX idx_agent_runs_status_created ON agent_runs (status, created_at DESC)",
            """
            CREATE TABLE agent_run_events (
                run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                step TEXT,
                attempt INTEGER,
                occurred_at TEXT NOT NULL,
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                PRIMARY KEY (run_id, seq)
            )
            """,
            """
            CREATE TABLE agent_checkpoints (
                run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                step_index INTEGER NOT NULL DEFAULT 0,
                checkpoint_kind TEXT NOT NULL DEFAULT 'step',
                state_json JSONB NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (run_id, name)
            )
            """,
            """
            CREATE TABLE rag_index_releases (
                release_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK (status IN ('building', 'active', 'retired', 'failed')),
                corpus_digest TEXT NOT NULL,
                chunking_version TEXT NOT NULL,
                embedding_provider TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
                chunk_count INTEGER NOT NULL CHECK (chunk_count >= 0),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                activated_at TIMESTAMPTZ,
                retired_at TIMESTAMPTZ
            )
            """,
            """
            CREATE TABLE rag_chunks (
                release_id TEXT NOT NULL REFERENCES rag_index_releases(release_id) ON DELETE CASCADE,
                chunk_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                document_version TEXT NOT NULL,
                source TEXT NOT NULL,
                heading TEXT NOT NULL,
                text TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                source_url TEXT,
                published_at TEXT,
                reviewed_at TEXT,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                embedding vector NOT NULL,
                PRIMARY KEY (release_id, chunk_id)
            )
            """,
            "CREATE INDEX idx_rag_chunks_release_hash ON rag_chunks (release_id, content_hash)",
            """
            CREATE TABLE rag_active_pointer (
                slot TEXT PRIMARY KEY CHECK (slot = 'default'),
                active_release_id TEXT NOT NULL REFERENCES rag_index_releases(release_id),
                previous_release_id TEXT REFERENCES rag_index_releases(release_id),
                switched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        ),
    ),
)
