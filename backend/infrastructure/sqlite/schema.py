from backend.infrastructure.sqlite.migrations import Migration


def _json_shape_triggers(
    table_name: str, columns: tuple[tuple[str, str], ...]
) -> tuple[str, ...]:
    checks = "\n                OR ".join(
        f"(CASE WHEN json_valid(NEW.{column_name}) "
        f"THEN json_type(NEW.{column_name}) <> '{shape}' ELSE 0 END)"
        for column_name, shape in columns
    )
    column_names = ", ".join(column_name for column_name, _ in columns)
    events = (
        ("insert", "INSERT"),
        ("update", f"UPDATE OF {column_names}"),
    )
    return tuple(
        f"""
            CREATE TRIGGER {table_name}_json_shape_{suffix}
            BEFORE {event} ON {table_name}
            WHEN {checks}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} JSON shape mismatch');
            END
            """
        for suffix, event in events
    )


RECORDS_MIGRATIONS = (
    Migration(
        version=1,
        name="create_records_schema",
        statements=(
            """
            CREATE TABLE data_migrations (
                migration_key TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
                source_backup_path TEXT,
                details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details_json)),
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
            """,
            """
            CREATE TABLE user_profile_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                age INTEGER NOT NULL CHECK (age >= 18 AND age <= 100),
                height_cm REAL NOT NULL CHECK (height_cm >= 120 AND height_cm <= 230),
                weight_kg REAL NOT NULL CHECK (weight_kg >= 30 AND weight_kg <= 300),
                energy_parameter TEXT NOT NULL CHECK (energy_parameter IN ('male', 'female', 'neutral')),
                activity_level TEXT NOT NULL CHECK (activity_level IN ('sedentary', 'light', 'moderate', 'high')),
                auto_target_disabled INTEGER NOT NULL DEFAULT 0 CHECK (auto_target_disabled IN (0, 1)),
                safety_conditions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(safety_conditions_json)),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE UNIQUE INDEX idx_profile_versions_user_id ON user_profile_versions(user_id, id)",
            """
            CREATE TABLE overall_goal_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                goal TEXT NOT NULL CHECK (goal IN ('fat_loss', 'maintenance', 'muscle_gain')),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE UNIQUE INDEX idx_goal_versions_user_id ON overall_goal_versions(user_id, id)",
            """
            CREATE TABLE daily_target_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                profile_version_id TEXT,
                overall_goal_version_id TEXT,
                calories REAL NOT NULL CHECK (calories >= 800 AND calories <= 6000),
                carbs REAL NOT NULL CHECK (carbs >= 0 AND carbs <= 1000),
                protein REAL NOT NULL CHECK (protein >= 20 AND protein <= 400),
                fat REAL NOT NULL CHECK (fat >= 10 AND fat <= 300),
                source TEXT NOT NULL CHECK (source IN ('deterministic_calculation', 'manual', 'agent_confirmed')),
                formula_version TEXT,
                rationale_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(rationale_json)),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id, profile_version_id) REFERENCES user_profile_versions(user_id, id) ON DELETE RESTRICT,
                FOREIGN KEY(user_id, overall_goal_version_id) REFERENCES overall_goal_versions(user_id, id) ON DELETE RESTRICT,
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE UNIQUE INDEX idx_target_versions_user_id ON daily_target_versions(user_id, id)",
            "CREATE INDEX idx_target_versions_profile ON daily_target_versions(user_id, profile_version_id)",
            "CREATE INDEX idx_target_versions_goal ON daily_target_versions(user_id, overall_goal_version_id)",
            """
            CREATE TABLE daily_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                planned_meal_count INTEGER NOT NULL DEFAULT 3 CHECK (planned_meal_count >= 1 AND planned_meal_count <= 12),
                target_version_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id, target_version_id) REFERENCES daily_target_versions(user_id, id) ON DELETE RESTRICT,
                UNIQUE(user_id, log_date)
            )
            """,
            "CREATE INDEX idx_daily_logs_target ON daily_logs(user_id, target_version_id)",
            """
            CREATE TABLE food_catalog (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT,
                source TEXT NOT NULL CHECK (source IN ('public', 'user_custom', 'agent_estimate', 'legacy_import')),
                source_name TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                dataset_version TEXT,
                name TEXT NOT NULL,
                basis_type TEXT NOT NULL CHECK (basis_type IN ('per_100g', 'per_100ml', 'per_serving')),
                basis_amount REAL NOT NULL CHECK (basis_amount > 0),
                unit TEXT NOT NULL,
                calories REAL NOT NULL CHECK (calories >= 0),
                carbs REAL NOT NULL CHECK (carbs >= 0),
                protein REAL NOT NULL CHECK (protein >= 0),
                fat REAL NOT NULL CHECK (fat >= 0),
                license TEXT,
                attribution TEXT,
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                content_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
            """
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
                secondary_muscles_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(secondary_muscles_json)),
                met REAL CHECK (met IS NULL OR met > 0),
                license TEXT,
                attribution TEXT,
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                content_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
                CHECK ((food_id IS NOT NULL) != (exercise_id IS NOT NULL))
            )
            """,
            "CREATE INDEX idx_catalog_alias_food ON catalog_aliases(food_id)",
            "CREATE INDEX idx_catalog_alias_exercise ON catalog_aliases(exercise_id)",
            "CREATE INDEX idx_catalog_alias_normalized ON catalog_aliases(normalized_alias)",
            """
            CREATE TABLE catalog_favorites (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                food_id TEXT,
                exercise_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(food_id) REFERENCES food_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(exercise_id) REFERENCES exercise_catalog(id) ON DELETE CASCADE,
                CHECK ((food_id IS NOT NULL) != (exercise_id IS NOT NULL))
            )
            """,
            "CREATE UNIQUE INDEX idx_catalog_favorites_user_food ON catalog_favorites(user_id, food_id) WHERE food_id IS NOT NULL",
            "CREATE UNIQUE INDEX idx_catalog_favorites_user_exercise ON catalog_favorites(user_id, exercise_id) WHERE exercise_id IS NOT NULL",
            "CREATE INDEX idx_catalog_favorites_food ON catalog_favorites(food_id)",
            "CREATE INDEX idx_catalog_favorites_exercise ON catalog_favorites(exercise_id)",
            """
            CREATE TABLE catalog_usage (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                food_id TEXT,
                exercise_id TEXT,
                use_count INTEGER NOT NULL DEFAULT 1 CHECK (use_count >= 1),
                last_used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(food_id) REFERENCES food_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(exercise_id) REFERENCES exercise_catalog(id) ON DELETE CASCADE,
                CHECK ((food_id IS NOT NULL) != (exercise_id IS NOT NULL))
            )
            """,
            "CREATE UNIQUE INDEX idx_catalog_usage_user_food ON catalog_usage(user_id, food_id) WHERE food_id IS NOT NULL",
            "CREATE UNIQUE INDEX idx_catalog_usage_user_exercise ON catalog_usage(user_id, exercise_id) WHERE exercise_id IS NOT NULL",
            "CREATE INDEX idx_catalog_usage_food ON catalog_usage(food_id)",
            "CREATE INDEX idx_catalog_usage_exercise ON catalog_usage(exercise_id)",
            "CREATE INDEX idx_catalog_usage_recent ON catalog_usage(user_id, last_used_at DESC)",
            """
            CREATE TABLE record_drafts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('meal', 'workout', 'smart_entry', 'daily_target')),
                schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
                payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                agent_status TEXT NOT NULL DEFAULT 'not_requested' CHECK (agent_status IN ('not_requested', 'running', 'completed', 'failed')),
                agent_prompt_version TEXT,
                agent_model TEXT,
                agent_metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(agent_metadata_json)),
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX idx_record_drafts_user_expiry ON record_drafts(user_id, expires_at)",
            """
            CREATE TABLE meals (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                name TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                position INTEGER NOT NULL CHECK (position >= 1),
                entry_method TEXT NOT NULL CHECK (entry_method IN ('form', 'smart_entry', 'csv', 'legacy')),
                legacy_source_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, log_date, position)
            )
            """,
            """
            CREATE TABLE meal_items (
                id TEXT PRIMARY KEY,
                meal_id TEXT NOT NULL,
                catalog_food_id TEXT,
                food_name TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                unit TEXT NOT NULL,
                basis_type TEXT NOT NULL CHECK (basis_type IN ('per_100g', 'per_100ml', 'per_serving')),
                calories REAL NOT NULL CHECK (calories >= 0),
                carbs REAL NOT NULL CHECK (carbs >= 0),
                protein REAL NOT NULL CHECK (protein >= 0),
                fat REAL NOT NULL CHECK (fat >= 0),
                source TEXT NOT NULL CHECK (source IN ('public', 'user_custom', 'agent_estimate', 'legacy_import')),
                is_estimate INTEGER NOT NULL DEFAULT 0 CHECK (is_estimate IN (0, 1)),
                uncertainty_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(uncertainty_json)),
                assumptions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(assumptions_json)),
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(meal_id) REFERENCES meals(id) ON DELETE CASCADE,
                FOREIGN KEY(catalog_food_id) REFERENCES food_catalog(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX idx_meal_items_meal ON meal_items(meal_id)",
            "CREATE INDEX idx_meal_items_catalog ON meal_items(catalog_food_id)",
            """
            CREATE TABLE training_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                title TEXT NOT NULL,
                started_at TEXT,
                duration_min REAL CHECK (duration_min IS NULL OR duration_min > 0),
                intensity TEXT CHECK (intensity IS NULL OR intensity IN ('low', 'medium', 'high')),
                entry_method TEXT NOT NULL CHECK (entry_method IN ('form', 'smart_entry', 'csv', 'legacy')),
                estimated_calories REAL CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(estimate_json)),
                legacy_source_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                secondary_muscles_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(secondary_muscles_json)),
                estimated_calories REAL CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(estimate_json)),
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
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
                load_kg REAL CHECK (load_kg IS NULL OR load_kg >= 0),
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
                duration_min REAL NOT NULL CHECK (duration_min > 0),
                device_calories REAL CHECK (device_calories IS NULL OR device_calories >= 0),
                met REAL CHECK (met IS NULL OR met > 0),
                estimated_calories REAL CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(estimate_json)),
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                position INTEGER NOT NULL CHECK (position >= 1),
                FOREIGN KEY(session_id) REFERENCES training_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(catalog_exercise_id) REFERENCES exercise_catalog(id) ON DELETE SET NULL,
                UNIQUE(session_id, position)
            )
            """,
            "CREATE INDEX idx_cardio_items_catalog ON cardio_items(catalog_exercise_id)",
            """
            CREATE TABLE idempotency_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                response_json TEXT NOT NULL CHECK (json_valid(response_json)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, operation, idempotency_key)
            )
            """,
            """
            CREATE TABLE catalog_imports (
                source_name TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                checksum TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
                imported_count INTEGER NOT NULL DEFAULT 0 CHECK (imported_count >= 0),
                rejected_count INTEGER NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
                details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details_json)),
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                PRIMARY KEY(source_name, dataset_version)
            )
            """,
            """
            CREATE VIRTUAL TABLE catalog_search USING fts5(
                catalog_kind UNINDEXED,
                catalog_id UNINDEXED,
                name,
                aliases,
                pinyin,
                source_tokens
            )
            """,
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
            SELECT SUM(violations)
            FROM (
                SELECT COUNT(*) AS violations
                FROM catalog_favorites AS favorite
                WHERE favorite.food_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM food_catalog AS food
                    WHERE food.id = favorite.food_id
                      AND (
                        food.owner_user_id IS NULL
                        OR food.owner_user_id = favorite.user_id
                      )
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM catalog_favorites AS favorite
                WHERE favorite.exercise_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM exercise_catalog AS exercise
                    WHERE exercise.id = favorite.exercise_id
                      AND (
                        exercise.owner_user_id IS NULL
                        OR exercise.owner_user_id = favorite.user_id
                      )
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM catalog_usage AS usage
                WHERE usage.food_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM food_catalog AS food
                    WHERE food.id = usage.food_id
                      AND (
                        food.owner_user_id IS NULL
                        OR food.owner_user_id = usage.user_id
                      )
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM catalog_usage AS usage
                WHERE usage.exercise_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM exercise_catalog AS exercise
                    WHERE exercise.id = usage.exercise_id
                      AND (
                        exercise.owner_user_id IS NULL
                        OR exercise.owner_user_id = usage.user_id
                      )
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM meal_items AS item
                WHERE item.catalog_food_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM meals AS meal
                    JOIN food_catalog AS food
                      ON food.id = item.catalog_food_id
                    WHERE meal.id = item.meal_id
                      AND (
                        food.owner_user_id IS NULL
                        OR food.owner_user_id = meal.user_id
                      )
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM strength_exercises AS item
                WHERE item.catalog_exercise_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM training_sessions AS session
                    JOIN exercise_catalog AS exercise
                      ON exercise.id = item.catalog_exercise_id
                    WHERE session.id = item.session_id
                      AND exercise.exercise_type = 'strength'
                      AND (
                        exercise.owner_user_id IS NULL
                        OR exercise.owner_user_id = session.user_id
                      )
                  )
                UNION ALL
                SELECT COUNT(*)
                FROM cardio_items AS item
                WHERE item.catalog_exercise_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM training_sessions AS session
                    JOIN exercise_catalog AS exercise
                      ON exercise.id = item.catalog_exercise_id
                    WHERE session.id = item.session_id
                      AND exercise.exercise_type = 'cardio'
                      AND (
                        exercise.owner_user_id IS NULL
                        OR exercise.owner_user_id = session.user_id
                      )
                  )
                UNION ALL
                SELECT COUNT(*) FROM data_migrations
                WHERE CASE WHEN json_valid(details_json)
                    THEN json_type(details_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM user_profile_versions
                WHERE CASE WHEN json_valid(safety_conditions_json)
                    THEN json_type(safety_conditions_json) IS NOT 'array' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM daily_target_versions
                WHERE CASE WHEN json_valid(rationale_json)
                    THEN json_type(rationale_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM food_catalog
                WHERE CASE WHEN json_valid(provenance_json)
                    THEN json_type(provenance_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM exercise_catalog
                WHERE CASE WHEN json_valid(secondary_muscles_json)
                    THEN json_type(secondary_muscles_json) IS NOT 'array' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM exercise_catalog
                WHERE CASE WHEN json_valid(provenance_json)
                    THEN json_type(provenance_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM record_drafts
                WHERE CASE WHEN json_valid(payload_json)
                    THEN json_type(payload_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM record_drafts
                WHERE CASE WHEN json_valid(agent_metadata_json)
                    THEN json_type(agent_metadata_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM meal_items
                WHERE CASE WHEN json_valid(uncertainty_json)
                    THEN json_type(uncertainty_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM meal_items
                WHERE CASE WHEN json_valid(assumptions_json)
                    THEN json_type(assumptions_json) IS NOT 'array' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM meal_items
                WHERE CASE WHEN json_valid(provenance_json)
                    THEN json_type(provenance_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM training_sessions
                WHERE CASE WHEN json_valid(estimate_json)
                    THEN json_type(estimate_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM strength_exercises
                WHERE CASE WHEN json_valid(secondary_muscles_json)
                    THEN json_type(secondary_muscles_json) IS NOT 'array' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM strength_exercises
                WHERE CASE WHEN json_valid(estimate_json)
                    THEN json_type(estimate_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM strength_exercises
                WHERE CASE WHEN json_valid(provenance_json)
                    THEN json_type(provenance_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM cardio_items
                WHERE CASE WHEN json_valid(estimate_json)
                    THEN json_type(estimate_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM cardio_items
                WHERE CASE WHEN json_valid(provenance_json)
                    THEN json_type(provenance_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM idempotency_keys
                WHERE CASE WHEN json_valid(response_json)
                    THEN json_type(response_json) IS NOT 'object' ELSE 1 END
                UNION ALL
                SELECT COUNT(*) FROM catalog_imports
                WHERE CASE WHEN json_valid(details_json)
                    THEN json_type(details_json) IS NOT 'object' ELSE 1 END
            )
            """,
            """
            CREATE TRIGGER food_catalog_partition_immutable
            BEFORE UPDATE OF owner_user_id, source ON food_catalog
            WHEN NEW.owner_user_id IS NOT OLD.owner_user_id
              OR NEW.source IS NOT OLD.source
            BEGIN
                SELECT RAISE(ABORT, 'food catalog ownership is immutable');
            END
            """,
            """
            CREATE TRIGGER exercise_catalog_partition_type_immutable
            BEFORE UPDATE OF owner_user_id, source, exercise_type ON exercise_catalog
            WHEN NEW.owner_user_id IS NOT OLD.owner_user_id
              OR NEW.source IS NOT OLD.source
              OR NEW.exercise_type IS NOT OLD.exercise_type
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'exercise catalog ownership and type are immutable'
                );
            END
            """,
            """
            CREATE TRIGGER catalog_favorites_visible_insert
            BEFORE INSERT ON catalog_favorites
            WHEN (
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
            )
            BEGIN
                SELECT RAISE(ABORT, 'catalog favorite is not visible to user');
            END
            """,
            """
            CREATE TRIGGER catalog_favorites_visible_update
            BEFORE UPDATE OF user_id, food_id, exercise_id ON catalog_favorites
            WHEN (
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
            )
            BEGIN
                SELECT RAISE(ABORT, 'catalog favorite is not visible to user');
            END
            """,
            """
            CREATE TRIGGER catalog_usage_visible_insert
            BEFORE INSERT ON catalog_usage
            WHEN (
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
            )
            BEGIN
                SELECT RAISE(ABORT, 'catalog usage is not visible to user');
            END
            """,
            """
            CREATE TRIGGER catalog_usage_visible_update
            BEFORE UPDATE OF user_id, food_id, exercise_id ON catalog_usage
            WHEN (
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
            )
            BEGIN
                SELECT RAISE(ABORT, 'catalog usage is not visible to user');
            END
            """,
            """
            CREATE TRIGGER meals_owner_immutable
            BEFORE UPDATE OF user_id ON meals
            WHEN NEW.user_id IS NOT OLD.user_id
            BEGIN
                SELECT RAISE(ABORT, 'meal owner is immutable');
            END
            """,
            """
            CREATE TRIGGER meal_items_visible_insert
            BEFORE INSERT ON meal_items
            WHEN NEW.catalog_food_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1
                FROM meals AS meal
                JOIN food_catalog AS food ON food.id = NEW.catalog_food_id
                WHERE meal.id = NEW.meal_id
                  AND (
                    food.owner_user_id IS NULL
                    OR food.owner_user_id = meal.user_id
                  )
             )
            BEGIN
                SELECT RAISE(ABORT, 'catalog food is not visible to meal owner');
            END
            """,
            """
            CREATE TRIGGER meal_items_visible_update
            BEFORE UPDATE OF meal_id, catalog_food_id ON meal_items
            WHEN NEW.catalog_food_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1
                FROM meals AS meal
                JOIN food_catalog AS food ON food.id = NEW.catalog_food_id
                WHERE meal.id = NEW.meal_id
                  AND (
                    food.owner_user_id IS NULL
                    OR food.owner_user_id = meal.user_id
                  )
             )
            BEGIN
                SELECT RAISE(ABORT, 'catalog food is not visible to meal owner');
            END
            """,
            """
            CREATE TRIGGER training_sessions_owner_immutable
            BEFORE UPDATE OF user_id ON training_sessions
            WHEN NEW.user_id IS NOT OLD.user_id
            BEGIN
                SELECT RAISE(ABORT, 'training session owner is immutable');
            END
            """,
            """
            CREATE TRIGGER strength_exercises_catalog_insert
            BEFORE INSERT ON strength_exercises
            WHEN NEW.catalog_exercise_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1
                FROM training_sessions AS session
                JOIN exercise_catalog AS exercise
                  ON exercise.id = NEW.catalog_exercise_id
                WHERE session.id = NEW.session_id
                  AND exercise.exercise_type = 'strength'
                  AND (
                    exercise.owner_user_id IS NULL
                    OR exercise.owner_user_id = session.user_id
                  )
             )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'catalog exercise must be visible strength exercise'
                );
            END
            """,
            """
            CREATE TRIGGER strength_exercises_catalog_update
            BEFORE UPDATE OF session_id, catalog_exercise_id ON strength_exercises
            WHEN NEW.catalog_exercise_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1
                FROM training_sessions AS session
                JOIN exercise_catalog AS exercise
                  ON exercise.id = NEW.catalog_exercise_id
                WHERE session.id = NEW.session_id
                  AND exercise.exercise_type = 'strength'
                  AND (
                    exercise.owner_user_id IS NULL
                    OR exercise.owner_user_id = session.user_id
                  )
             )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'catalog exercise must be visible strength exercise'
                );
            END
            """,
            """
            CREATE TRIGGER cardio_items_catalog_insert
            BEFORE INSERT ON cardio_items
            WHEN NEW.catalog_exercise_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1
                FROM training_sessions AS session
                JOIN exercise_catalog AS exercise
                  ON exercise.id = NEW.catalog_exercise_id
                WHERE session.id = NEW.session_id
                  AND exercise.exercise_type = 'cardio'
                  AND (
                    exercise.owner_user_id IS NULL
                    OR exercise.owner_user_id = session.user_id
                  )
             )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'catalog exercise must be visible cardio exercise'
                );
            END
            """,
            """
            CREATE TRIGGER cardio_items_catalog_update
            BEFORE UPDATE OF session_id, catalog_exercise_id ON cardio_items
            WHEN NEW.catalog_exercise_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1
                FROM training_sessions AS session
                JOIN exercise_catalog AS exercise
                  ON exercise.id = NEW.catalog_exercise_id
                WHERE session.id = NEW.session_id
                  AND exercise.exercise_type = 'cardio'
                  AND (
                    exercise.owner_user_id IS NULL
                    OR exercise.owner_user_id = session.user_id
                  )
             )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'catalog exercise must be visible cardio exercise'
                );
            END
            """,
            *_json_shape_triggers(
                "data_migrations", (("details_json", "object"),)
            ),
            *_json_shape_triggers(
                "user_profile_versions",
                (("safety_conditions_json", "array"),),
            ),
            *_json_shape_triggers(
                "daily_target_versions", (("rationale_json", "object"),)
            ),
            *_json_shape_triggers(
                "food_catalog", (("provenance_json", "object"),)
            ),
            *_json_shape_triggers(
                "exercise_catalog",
                (
                    ("secondary_muscles_json", "array"),
                    ("provenance_json", "object"),
                ),
            ),
            *_json_shape_triggers(
                "record_drafts",
                (
                    ("payload_json", "object"),
                    ("agent_metadata_json", "object"),
                ),
            ),
            *_json_shape_triggers(
                "meal_items",
                (
                    ("uncertainty_json", "object"),
                    ("assumptions_json", "array"),
                    ("provenance_json", "object"),
                ),
            ),
            *_json_shape_triggers(
                "training_sessions", (("estimate_json", "object"),)
            ),
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
                (
                    ("estimate_json", "object"),
                    ("provenance_json", "object"),
                ),
            ),
            *_json_shape_triggers(
                "idempotency_keys", (("response_json", "object"),)
            ),
            *_json_shape_triggers(
                "catalog_imports", (("details_json", "object"),)
            ),
            # source_tokens contains full normalized terms and overlapping
            # bigrams so exact Chinese terms and shorter phrases both match.
            """
            CREATE VIRTUAL TABLE catalog_search_v2 USING fts5(
                catalog_kind UNINDEXED,
                catalog_id UNINDEXED,
                name,
                aliases,
                pinyin,
                source_tokens,
                tokenize = 'unicode61 remove_diacritics 2',
                prefix = '2 3 4'
            )
            """,
            """
            INSERT INTO catalog_search_v2 (
                rowid, catalog_kind, catalog_id, name, aliases, pinyin,
                source_tokens
            )
            SELECT
                rowid, catalog_kind, catalog_id, name, aliases, pinyin,
                source_tokens
            FROM catalog_search
            """,
            "DROP TABLE catalog_search",
            "ALTER TABLE catalog_search_v2 RENAME TO catalog_search",
            "DROP TABLE records_v2_migration_guard",
        ),
    ),
)
