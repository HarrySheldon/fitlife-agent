from backend.infrastructure.sqlite.migrations import Migration


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
)
