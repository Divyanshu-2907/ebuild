import pytest
import yaml

from ebuild.core.config import ConfigError, load_config


def write_config(tmp_path, data):
    config_path = tmp_path / "build.yaml"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return config_path


@pytest.mark.parametrize("invalid_target", ["app", 42, None])
def test_target_definition_must_be_mapping(tmp_path, invalid_target):
    path = write_config(
        tmp_path,
        {"project": {"name": "demo"}, "targets": [invalid_target]},
    )

    with pytest.raises(ConfigError, match="expected a YAML mapping"):
        load_config(path)


@pytest.mark.parametrize("field_name", [
    "sources", "includes", "cflags", "ldflags", "defines", "depends", "uses"
])
def test_target_collection_fields_must_be_lists(tmp_path, field_name):
    target = {"name": "app", "type": "executable", "sources": ["main.c"]}
    target[field_name] = "not-a-list"
    path = write_config(
        tmp_path,
        {"project": {"name": "demo"}, "targets": [target]},
    )

    with pytest.raises(ConfigError, match=rf"field '{field_name}' must be a list"):
        load_config(path)


def test_target_collection_items_must_be_strings(tmp_path):
    path = write_config(
        tmp_path,
        {
            "project": {"name": "demo"},
            "targets": [
                {"name": "app", "type": "executable", "sources": ["main.c", 7]}
            ],
        },
    )

    with pytest.raises(ConfigError, match="must contain only strings"):
        load_config(path)


def test_backend_config_must_be_mapping(tmp_path):
    path = write_config(
        tmp_path,
        {"project": {"name": "demo"}, "backend_config": ["invalid"]},
    )

    with pytest.raises(ConfigError, match="'backend_config' must be a mapping"):
        load_config(path)


def test_toolchain_must_be_mapping(tmp_path):
    path = write_config(
        tmp_path,
        {"project": {"name": "demo"}, "toolchain": "arm-none-eabi"},
    )

    with pytest.raises(ConfigError, match="'toolchain' must be a mapping"):
        load_config(path)


def test_toolchain_mapping_is_parsed(tmp_path):
    path = write_config(
        tmp_path,
        {
            "project": {"name": "demo"},
            "toolchain": {
                "compiler": "arm-none-eabi",
                "arch": "arm",
                "prefix": "arm-none-eabi-",
                "sysroot": "/opt/arm-none-eabi",
                "extra_cflags": ["-mcpu=cortex-m4"],
                "extra_ldflags": ["--specs=nosys.specs"],
            },
        },
    )

    config = load_config(path)

    assert config.toolchain is not None
    assert config.toolchain.compiler == "arm-none-eabi"
    assert config.toolchain.arch == "arm"
    assert config.toolchain.prefix == "arm-none-eabi-"
    assert config.toolchain.sysroot == "/opt/arm-none-eabi"
    assert config.toolchain.extra_cflags == ["-mcpu=cortex-m4"]
    assert config.toolchain.extra_ldflags == ["--specs=nosys.specs"]


@pytest.mark.parametrize("invalid_packages", [
    {"name": "zlib", "version": "1.2.13"},
    "zlib",
    42,
])
def test_packages_must_be_a_list(tmp_path, invalid_packages):
    path = write_config(
        tmp_path,
        {"project": {"name": "demo"}, "packages": invalid_packages},
    )

    with pytest.raises(ConfigError, match="'packages' must be a list"):
        load_config(path)


@pytest.mark.parametrize("invalid_item", ["zlib", 42, None])
def test_package_definition_must_be_mapping(tmp_path, invalid_item):
    path = write_config(
        tmp_path,
        {"project": {"name": "demo"}, "packages": [invalid_item]},
    )

    with pytest.raises(ConfigError, match="expected a YAML mapping"):
        load_config(path)


def test_package_definition_requires_name(tmp_path):
    path = write_config(
        tmp_path,
        {
            "project": {"name": "demo"},
            "packages": [{"version": "1.2.13"}],
        },
    )

    with pytest.raises(ConfigError, match="must have a 'name'"):
        load_config(path)


def test_packages_list_is_parsed(tmp_path):
    path = write_config(
        tmp_path,
        {
            "project": {"name": "demo"},
            "packages": [
                {"name": "zlib", "version": "1.2.13"},
                {"name": "mbedtls"},
            ],
        },
    )

    config = load_config(path)

    assert len(config.packages) == 2
    assert config.packages[0].name == "zlib"
    assert config.packages[0].version == "1.2.13"
    assert config.packages[1].name == "mbedtls"
    assert config.packages[1].version is None


def test_omitted_packages_is_empty(tmp_path):
    path = write_config(tmp_path, {"project": {"name": "demo"}})
    config = load_config(path)
    assert config.packages == []
