"""
json_registry.py - Master JSON Schema Registry for Chameleon
Inspired by the master DB design pattern with unified JSON management:
  - Unified registry of all JSON types
  - Category classification (ARTIFACT / CORE_SCHEMA / RUNTIME_STATE)
  - Dependency graph (directed acyclic graph)
  - Generation rules
  - Validation rules
  - Access control matrix
  - Integrity constraints
  - Monitoring metrics
  - Backup strategy
  - Version differentiation (SemVer / Timestamp)
"""

from dataclasses import dataclass, field
from enum import Enum


class JsonCategory(Enum):
    ARTIFACT      = "ARTIFACT"       # 公開後不変: append-only logs
    CORE_SCHEMA   = "CORE_SCHEMA"    # 慎重変更: versioned configs/cache
    RUNTIME_STATE = "RUNTIME_STATE"  # 揮発性: in-memory API responses


class VersionStrategy(Enum):
    SEMVER      = "SemVer"       # 1.0.0 — stable schemas
    INCREMENTAL = "Incremental"  # auto-increment — operational data
    TIMESTAMP   = "Timestamp"    # ISO datetime — logs and runtime


@dataclass
class JsonSchema:
    json_type:          str
    category:           JsonCategory
    version:            str
    version_strategy:   VersionStrategy
    path_pattern:       str
    description:        str
    required_fields:    list[str]
    optional_fields:    list[str]       = field(default_factory=list)
    field_types:        dict[str, type] = field(default_factory=dict)
    field_constraints:  dict[str, dict] = field(default_factory=dict)
    dependencies:       list[str]       = field(default_factory=list)
    generated_by:       list[str]       = field(default_factory=list)
    read_modules:       list[str]       = field(default_factory=list)
    write_modules:      list[str]       = field(default_factory=list)
    generation_rule:    str             = ""
    notes:              str             = ""


# ── Category Definitions ──────────────────────────────────────────────────────

CATEGORY_DEFINITIONS = {
    JsonCategory.ARTIFACT: {
        "description":  "公開後不変。追記のみ許可。削除・上書き禁止。",
        "mutability":   "append-only",
        "versioning":   "timestamp",
        "examples":     ["decisions.jsonl", "api_usage.jsonl", "cycle_summary.jsonl"],
    },
    JsonCategory.CORE_SCHEMA: {
        "description":  "慎重な変更のみ許可。バージョン管理必須。",
        "mutability":   "versioned-update",
        "versioning":   "semver",
        "examples":     ["universe.json", "mock_data/*.json"],
    },
    JsonCategory.RUNTIME_STATE: {
        "description":  "揮発性。サイクルごとに上書き。永続化不要。",
        "mutability":   "volatile",
        "versioning":   "timestamp",
        "examples":     ["nansen_holdings (in-memory)", "nansen_netflow (in-memory)"],
    },
}


# ── Master JSON Registry ──────────────────────────────────────────────────────

JSON_REGISTRY: dict[str, JsonSchema] = {

    # ── UNIVERSE (watchlist cache) ─────────────────────────────────────────
    "UNIVERSE": JsonSchema(
        json_type         = "UNIVERSE",
        category          = JsonCategory.CORE_SCHEMA,
        version           = "1.0.0",
        version_strategy  = VersionStrategy.SEMVER,
        path_pattern      = "cache/universe.json",
        description       = "ウォッチリスト・クールダウン・ブラックリストの永続キャッシュ",
        required_fields   = ["watchlist", "cooldown", "blacklist", "updated_at"],
        optional_fields   = ["schema_version"],
        field_types       = {
            "watchlist":  dict,
            "cooldown":   dict,
            "blacklist":  list,
            "updated_at": str,
        },
        field_constraints = {
            "updated_at": {"format": "iso_datetime"},
            "watchlist":  {"value_type": dict},
            "blacklist":  {"item_type": str},
        },
        dependencies      = [],
        generated_by      = ["universe"],
        read_modules      = ["universe", "chameleon", "scanner"],
        write_modules     = ["universe", "chameleon"],
        generation_rule   = "scanner.scan()の結果をuniverse.add_to_watchlist()で追加。universe.save()で永続化。",
        notes             = "IC-001: watchlist内のトークンはblacklistに含まれていてはならない",
    ),

    # ── DECISION_LOG ──────────────────────────────────────────────────────
    "DECISION_LOG": JsonSchema(
        json_type         = "DECISION_LOG",
        category          = JsonCategory.ARTIFACT,
        version           = "1.1.0",
        version_strategy  = VersionStrategy.TIMESTAMP,
        path_pattern      = "logs/decisions.jsonl",
        description       = "全トークン判定の不変監査ログ (quality_score v1.1で追加)",
        required_fields   = ["timestamp", "cycle_id", "token", "chain", "mode", "action", "confidence", "reason"],
        optional_fields   = ["quality_score", "gate_details", "schema_version"],
        field_types       = {
            "timestamp":     str,
            "cycle_id":      str,
            "token":         str,
            "chain":         str,
            "mode":          str,
            "action":        str,
            "confidence":    float,
            "reason":        str,
            "quality_score": int,
        },
        field_constraints = {
            "timestamp":     {"format": "iso_datetime"},
            "mode":          {"enum": ["STEALTH", "CHASE", "ESCAPE", "SLEEP"]},
            "confidence":    {"min": 0.0, "max": 1.0},
            "token":         {"min_length": 4},
            "quality_score": {"min": 0, "max": 14},
        },
        dependencies      = ["NANSEN_HOLDINGS", "NANSEN_NETFLOW", "UNIVERSE"],
        generated_by      = ["api_usage_logger"],
        read_modules      = ["dashboard"],
        write_modules     = ["api_usage_logger"],
        generation_rule   = "chameleon.process_token()がstrategy.detect_mode()とquality_gate.evaluate()を実行後、log_decision()でARTIFACTとして追記。",
        notes             = "ARTIFACT: 一度書き込まれたエントリは変更・削除禁止",
    ),

    # ── API_USAGE_LOG ─────────────────────────────────────────────────────
    "API_USAGE_LOG": JsonSchema(
        json_type         = "API_USAGE_LOG",
        category          = JsonCategory.ARTIFACT,
        version           = "1.0.0",
        version_strategy  = VersionStrategy.TIMESTAMP,
        path_pattern      = "logs/api_usage.jsonl",
        description       = "Nansen APIコールの不変証拠ログ",
        required_fields   = ["timestamp", "cycle_id", "endpoint", "token", "chain", "status_code", "used_in_decision", "response_summary"],
        optional_fields   = ["schema_version"],
        field_types       = {
            "timestamp":        str,
            "cycle_id":         str,
            "endpoint":         str,
            "token":            str,
            "chain":            str,
            "status_code":      int,
            "used_in_decision": bool,
            "response_summary": dict,
        },
        field_constraints = {
            "timestamp":   {"format": "iso_datetime"},
            "status_code": {"min": 100, "max": 599},
        },
        dependencies      = [],
        generated_by      = ["api_usage_logger"],
        read_modules      = ["dashboard"],
        write_modules     = ["api_usage_logger"],
        generation_rule   = "nansen_client経由のAPIコールごとにlog_api_usage()で追記。",
        notes             = "ARTIFACT: Nansen APIクレジット使用の証拠。改ざん禁止。",
    ),

    # ── CYCLE_SUMMARY ─────────────────────────────────────────────────────
    "CYCLE_SUMMARY": JsonSchema(
        json_type         = "CYCLE_SUMMARY",
        category          = JsonCategory.ARTIFACT,
        version           = "1.1.0",
        version_strategy  = VersionStrategy.TIMESTAMP,
        path_pattern      = "logs/cycle_summary.jsonl",
        description       = "10分サイクルの集計サマリ不変ログ (quality_avg v1.1で追加)",
        required_fields   = ["timestamp", "cycle_id", "watchlist_size", "api_calls", "mode_counts"],
        optional_fields   = ["schema_version", "quality_avg"],
        field_types       = {
            "timestamp":      str,
            "cycle_id":       str,
            "watchlist_size": int,
            "api_calls":      int,
            "mode_counts":    dict,
            "quality_avg":    float,
        },
        field_constraints = {
            "timestamp":      {"format": "iso_datetime"},
            "watchlist_size": {"min": 0},
            "api_calls":      {"min": 0},
            "mode_counts": {
                "required_keys": ["STEALTH", "CHASE", "ESCAPE", "SLEEP"],
                "value_type": int,
            },
            "quality_avg": {"min": 0.0, "max": 14.0},
        },
        dependencies      = ["DECISION_LOG", "API_USAGE_LOG"],
        generated_by      = ["api_usage_logger"],
        read_modules      = ["dashboard"],
        write_modules     = ["api_usage_logger"],
        generation_rule   = "サイクル終了時にlog_cycle_summary()で集計して追記。",
    ),

    # ── MOCK_STEALTH ──────────────────────────────────────────────────────
    "MOCK_STEALTH": JsonSchema(
        json_type         = "MOCK_STEALTH",
        category          = JsonCategory.CORE_SCHEMA,
        version           = "1.0.0",
        version_strategy  = VersionStrategy.SEMVER,
        path_pattern      = "mock_data/stealth.json",
        description       = "STEALTHシナリオのテスト用モックデータ",
        required_fields   = ["token", "scenario", "holdings", "netflow", "price"],
        optional_fields   = ["dex_trades", "flow_intelligence"],
        field_types       = {"token": str, "scenario": str, "holdings": dict, "netflow": dict, "price": dict},
        field_constraints = {"scenario": {"enum": ["STEALTH", "CHASE", "ESCAPE", "SLEEP"]}},
        dependencies      = [],
        generated_by      = [],
        read_modules      = ["chameleon", "demo_run"],
        write_modules     = [],
        generation_rule   = "手動作成。スキーマ変更時はmigration_procedureに従う。",
    ),

    # ── MOCK_CHASE ────────────────────────────────────────────────────────
    "MOCK_CHASE": JsonSchema(
        json_type         = "MOCK_CHASE",
        category          = JsonCategory.CORE_SCHEMA,
        version           = "1.0.0",
        version_strategy  = VersionStrategy.SEMVER,
        path_pattern      = "mock_data/chase.json",
        description       = "CHASEシナリオのテスト用モックデータ",
        required_fields   = ["token", "scenario", "holdings", "netflow", "price"],
        optional_fields   = ["dex_trades", "flow_intelligence"],
        field_types       = {"token": str, "scenario": str, "holdings": dict, "netflow": dict, "price": dict},
        field_constraints = {"scenario": {"enum": ["STEALTH", "CHASE", "ESCAPE", "SLEEP"]}},
        dependencies      = [],
        generated_by      = [],
        read_modules      = ["chameleon", "demo_run"],
        write_modules     = [],
    ),

    # ── MOCK_ESCAPE ───────────────────────────────────────────────────────
    "MOCK_ESCAPE": JsonSchema(
        json_type         = "MOCK_ESCAPE",
        category          = JsonCategory.CORE_SCHEMA,
        version           = "1.0.0",
        version_strategy  = VersionStrategy.SEMVER,
        path_pattern      = "mock_data/escape.json",
        description       = "ESCAPEシナリオのテスト用モックデータ",
        required_fields   = ["token", "scenario", "holdings", "netflow", "price"],
        optional_fields   = ["dex_trades", "flow_intelligence"],
        field_types       = {"token": str, "scenario": str, "holdings": dict, "netflow": dict, "price": dict},
        field_constraints = {"scenario": {"enum": ["STEALTH", "CHASE", "ESCAPE", "SLEEP"]}},
        dependencies      = [],
        generated_by      = [],
        read_modules      = ["chameleon", "demo_run"],
        write_modules     = [],
    ),

    # ── MOCK_SLEEP ────────────────────────────────────────────────────────
    "MOCK_SLEEP": JsonSchema(
        json_type         = "MOCK_SLEEP",
        category          = JsonCategory.CORE_SCHEMA,
        version           = "1.0.0",
        version_strategy  = VersionStrategy.SEMVER,
        path_pattern      = "mock_data/sleep.json",
        description       = "SLEEPシナリオのテスト用モックデータ",
        required_fields   = ["token", "scenario", "holdings", "netflow", "price"],
        optional_fields   = ["dex_trades", "flow_intelligence"],
        field_types       = {"token": str, "scenario": str, "holdings": dict, "netflow": dict, "price": dict},
        field_constraints = {"scenario": {"enum": ["STEALTH", "CHASE", "ESCAPE", "SLEEP"]}},
        dependencies      = [],
        generated_by      = [],
        read_modules      = ["chameleon", "demo_run"],
        write_modules     = [],
    ),

    # ── NANSEN_HOLDINGS (runtime, in-memory) ──────────────────────────────
    "NANSEN_HOLDINGS": JsonSchema(
        json_type         = "NANSEN_HOLDINGS",
        category          = JsonCategory.RUNTIME_STATE,
        version           = "",
        version_strategy  = VersionStrategy.TIMESTAMP,
        path_pattern      = "(in-memory only)",
        description       = "Nansen smart-money/holdings APIのレスポンス（揮発性）",
        required_fields   = ["data"],
        optional_fields   = [],
        field_types       = {"data": list},
        field_constraints = {
            "data": {
                "item_fields": ["holders_count", "balance_24h_percent_change", "share_of_holdings_percent"],
            },
        },
        dependencies      = [],
        generated_by      = ["nansen_client"],
        read_modules      = ["strategy", "chameleon"],
        write_modules     = ["nansen_client"],
        generation_rule   = "nansen_client.fetch_all()内でAPIリクエスト。各サイクルで新規取得。",
        notes             = "RUNTIME_STATE: 永続化不要。次サイクルで上書き。",
    ),

    # ── NANSEN_NETFLOW (runtime, in-memory) ───────────────────────────────
    "NANSEN_NETFLOW": JsonSchema(
        json_type         = "NANSEN_NETFLOW",
        category          = JsonCategory.RUNTIME_STATE,
        version           = "",
        version_strategy  = VersionStrategy.TIMESTAMP,
        path_pattern      = "(in-memory only)",
        description       = "Nansen smart-money/netflow APIのレスポンス（揮発性）",
        required_fields   = ["data"],
        optional_fields   = [],
        field_types       = {"data": list},
        field_constraints = {
            "data": {
                "item_fields": ["net_flow_1h_usd", "net_flow_24h_usd", "net_flow_7d_usd", "trader_count"],
            },
        },
        dependencies      = [],
        generated_by      = ["nansen_client"],
        read_modules      = ["strategy", "chameleon"],
        write_modules     = ["nansen_client"],
        generation_rule   = "nansen_client.fetch_all()内でAPIリクエスト。各サイクルで新規取得。",
        notes             = "RUNTIME_STATE: 永続化不要。次サイクルで上書き。",
    ),
}


# ── Dependency Graph ──────────────────────────────────────────────────────────
# Layer 0: Source data (Nansen API / Mock files)
# Layer 1: RUNTIME_STATE (in-memory Nansen responses)
# Layer 2: Signal detection (strategy.detect_mode + quality_gate.evaluate)
# Layer 3: Decision with universe context
# Layer 4: ARTIFACT logs (write-once audit trail)
# Layer 5: Dashboard (read-only visualization)
#
# RULE: 上位レイヤーは下位レイヤーの入力スキーマを直接参照禁止
# e.g., dashboard は Nansen API を直接呼び出してはならない

DEPENDENCY_GRAPH: dict[str, list[str]] = {
    json_type: schema.dependencies
    for json_type, schema in JSON_REGISTRY.items()
}

LAYER_ARCHITECTURE = {
    0: ["Nansen_API", "Mock_Files"],
    1: ["NANSEN_HOLDINGS", "NANSEN_NETFLOW"],
    2: ["Signal_Detection (strategy + quality_gate)"],
    3: ["Decision (chameleon)", "UNIVERSE"],
    4: ["DECISION_LOG", "API_USAGE_LOG", "CYCLE_SUMMARY"],
    5: ["Dashboard (read-only)"],
}


# ── Integrity Constraints ─────────────────────────────────────────────────────

INTEGRITY_CONSTRAINTS = [
    {
        "id":          "IC-001",
        "description": "UNIVERSE.watchlistのトークンはUNIVERSE.blacklistに含まれていてはならない",
        "check":       "intersection(watchlist.keys(), blacklist) == empty",
        "severity":    "ERROR",
        "json_types":  ["UNIVERSE"],
    },
    {
        "id":          "IC-002",
        "description": "DECISION_LOG.confidenceは0.0以上1.0以下",
        "check":       "0.0 <= confidence <= 1.0",
        "severity":    "ERROR",
        "json_types":  ["DECISION_LOG"],
    },
    {
        "id":          "IC-003",
        "description": "DECISION_LOG.modeはSTEALTH/CHASE/ESCAPE/SLEEPのいずれか",
        "check":       "mode in VALID_MODES",
        "severity":    "ERROR",
        "json_types":  ["DECISION_LOG"],
    },
    {
        "id":          "IC-004",
        "description": "CYCLE_SUMMARY.mode_countsには4モード全てが含まれていなければならない",
        "check":       "set(mode_counts.keys()) >= {'STEALTH','CHASE','ESCAPE','SLEEP'}",
        "severity":    "WARNING",
        "json_types":  ["CYCLE_SUMMARY"],
    },
]


# ── Monitoring Metrics ────────────────────────────────────────────────────────

MONITORING_METRICS = {
    "api_calls_per_cycle": {
        "description":       "1サイクルあたりのNansen APIコール数",
        "target":            "< 50",
        "alert_threshold":   50,
        "source":            "CYCLE_SUMMARY.api_calls",
        "direction":         "lower_is_better",
    },
    "non_sleep_signal_rate": {
        "description":       "SLEEP以外のシグナル比率",
        "target":            "> 0.20",
        "alert_threshold":   0.05,
        "source":            "DECISION_LOG.mode",
        "direction":         "higher_is_better",
    },
    "decision_confidence_avg": {
        "description":       "判定信頼度の平均",
        "target":            "> 0.60",
        "alert_threshold":   0.40,
        "source":            "DECISION_LOG.confidence",
        "direction":         "higher_is_better",
    },
    "watchlist_size": {
        "description":       "ウォッチリストのトークン数",
        "target":            "5 – 20",
        "alert_threshold_min": 0,
        "alert_threshold_max": 50,
        "source":            "CYCLE_SUMMARY.watchlist_size",
        "direction":         "range",
    },
    "quality_gate_avg": {
        "description":       "品質ゲートスコアの平均 (0–14点)",
        "target":            "> 10",
        "alert_threshold":   7,
        "source":            "DECISION_LOG.quality_score",
        "direction":         "higher_is_better",
    },
    "schema_violation_count": {
        "description":       "スキーマ違反の累計件数",
        "target":            "0",
        "alert_threshold":   1,
        "source":            "schema_manager",
        "direction":         "lower_is_better",
    },
}


# ── Backup Strategy ───────────────────────────────────────────────────────────

BACKUP_STRATEGY = {
    JsonCategory.ARTIFACT: {
        "policy":     "永続保持。削除禁止。",
        "retention":  "無期限",
        "backup":     True,
        "note":       "ARTIFACT は監査証拠のため永久保存。",
    },
    JsonCategory.CORE_SCHEMA: {
        "policy":     "バージョン変更時にバックアップ作成。",
        "retention":  "90日",
        "backup":     True,
        "note":       "universe.json は毎サイクル上書き。変更前バックアップ推奨。",
    },
    JsonCategory.RUNTIME_STATE: {
        "policy":     "バックアップ不要。揮発性データ。",
        "retention":  "なし",
        "backup":     False,
        "note":       "RUNTIME_STATE は次サイクルで更新されるため保存不要。",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_schema(json_type: str) -> JsonSchema | None:
    return JSON_REGISTRY.get(json_type)


def get_schemas_by_category(category: JsonCategory) -> list[JsonSchema]:
    return [s for s in JSON_REGISTRY.values() if s.category == category]


def list_json_types() -> list[str]:
    return list(JSON_REGISTRY.keys())


def get_migration_template(json_type: str) -> dict:
    schema = JSON_REGISTRY.get(json_type)
    if not schema:
        return {}
    return {
        "json_type":       json_type,
        "current_version": schema.version,
        "category":        schema.category.value,
        "immutable":       schema.category == JsonCategory.ARTIFACT,
        "steps": [
            "1. 既存データをバックアップ (cp <path> <path>.bak)",
            "2. 新スキーマで空のデータ構造を作成",
            "3. 古いデータを新フィールドにマッピング",
            "4. validator.validate()で整合性確認",
            "5. バックアップ確認後、本番切り替え",
        ],
        "rollback": "バックアップファイルを元のパスに戻す",
    }
