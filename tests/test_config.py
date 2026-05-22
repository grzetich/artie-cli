"""Tests for .artie.toml configuration loading."""

import pytest

from artie.config import ArtieConfig, ConfigError, find_config, load_config

VALID_CONFIG = """\
ignore = ["Schema Complexity"]

[defaults]
with_generation = true
differential = false
model = "claude-haiku-4-5"
fail_under = 6

[thresholds]
"Format Efficiency" = 9
"Endpoint Completeness" = 8
"""


def write_config(directory, text):
    path = directory / ".artie.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadConfig:
    def test_no_file_returns_defaults(self, tmp_path):
        config = load_config(start=tmp_path)
        assert isinstance(config, ArtieConfig)
        assert config.thresholds == {}
        assert config.ignore == []
        assert config.fail_under is None
        assert config.with_generation is False
        assert config.source_path is None

    def test_valid_config(self, tmp_path):
        write_config(tmp_path, VALID_CONFIG)
        config = load_config(start=tmp_path)
        assert config.ignore == ["Schema Complexity"]
        assert config.with_generation is True
        assert config.differential is False
        assert config.model == "claude-haiku-4-5"
        assert config.fail_under == 6
        assert config.thresholds == {
            "Format Efficiency": 9,
            "Endpoint Completeness": 8,
        }
        assert config.source_path is not None
        assert not config.warnings

    def test_explicit_path(self, tmp_path):
        path = write_config(tmp_path, VALID_CONFIG)
        config = load_config(explicit=path)
        assert config.fail_under == 6

    def test_explicit_missing_path_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(explicit=tmp_path / "nope.toml")

    def test_invalid_toml_raises(self, tmp_path):
        write_config(tmp_path, "this is = = not toml")
        with pytest.raises(ConfigError, match="Invalid TOML"):
            load_config(start=tmp_path)

    def test_threshold_wrong_type_raises(self, tmp_path):
        write_config(tmp_path, '[thresholds]\n"Format Efficiency" = "high"\n')
        with pytest.raises(ConfigError, match="must be an integer"):
            load_config(start=tmp_path)

    def test_threshold_out_of_range_raises(self, tmp_path):
        write_config(tmp_path, '[thresholds]\n"Format Efficiency" = 15\n')
        with pytest.raises(ConfigError, match="must be 0-10"):
            load_config(start=tmp_path)

    def test_ignore_wrong_type_raises(self, tmp_path):
        write_config(tmp_path, 'ignore = "Schema Complexity"\n')
        with pytest.raises(ConfigError, match="list of check names"):
            load_config(start=tmp_path)

    def test_bad_default_flag_type_raises(self, tmp_path):
        write_config(tmp_path, '[defaults]\nwith_generation = "yes"\n')
        with pytest.raises(ConfigError, match="true or false"):
            load_config(start=tmp_path)

    def test_unknown_check_name_warns(self, tmp_path):
        write_config(tmp_path, '[thresholds]\n"Frmat Efficiency" = 9\n')
        config = load_config(start=tmp_path)
        assert config.warnings
        assert "Frmat Efficiency" in config.warnings[0]

    def test_known_check_names_do_not_warn(self, tmp_path):
        write_config(tmp_path, VALID_CONFIG)
        config = load_config(start=tmp_path)
        assert config.warnings == []


class TestFindConfig:
    def test_finds_in_current_directory(self, tmp_path):
        write_config(tmp_path, VALID_CONFIG)
        assert find_config(start=tmp_path) == tmp_path / ".artie.toml"

    def test_walks_up_to_parent(self, tmp_path):
        write_config(tmp_path, VALID_CONFIG)
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        assert find_config(start=nested) == tmp_path / ".artie.toml"

    def test_returns_none_when_absent(self, tmp_path):
        nested = tmp_path / "deep"
        nested.mkdir()
        # /tmp has no .artie.toml above it.
        assert find_config(start=nested) is None


class TestThresholdFor:
    def test_per_check_threshold_wins(self):
        config = ArtieConfig(thresholds={"Format Efficiency": 9}, fail_under=6)
        assert config.threshold_for("Format Efficiency") == 9

    def test_falls_back_to_global(self):
        config = ArtieConfig(thresholds={"Format Efficiency": 9}, fail_under=6)
        assert config.threshold_for("Auth Clarity") == 6

    def test_none_when_no_threshold_at_all(self):
        assert ArtieConfig().threshold_for("Auth Clarity") is None
