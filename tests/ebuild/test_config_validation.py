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


@pytest.mark.parametrize("field_name", ["extra_cflags", "extra_ldflags"])
def test_toolchain_extra_flag_fields_must_be_lists(tmp_path, field_name):
    path = write_config(
        tmp_path,
        {
            "project": {"name": "demo"},
            "toolchain": {
                "compiler": "arm-none-eabi",
                field_name: "-mcpu=cortex-m4",
            },
        },
    )

    with pytest.raises(
        ConfigError,
        match=rf"'toolchain\.{field_name}' must be a list",
    ):
        load_config(path)


@pytest.mark.parametrize("field_name", ["extra_cflags", "extra_ldflags"])
def test_toolchain_extra_flag_fields_must_contain_only_strings(
    tmp_path,
    field_name,
):
    path = write_config(
        tmp_path,
        {
            "project": {"name": "demo"},
            "toolchain": {
                "compiler": "arm-none-eabi",
                field_name: ["-mcpu=cortex-m4", 7],
            },
        },
    )

    with pytest.raises(
        ConfigError,
        match=rf"'toolchain\.{field_name}' must contain only strings",
    ):
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


def test_system_section_does_not_select_system_backend(tmp_path):
    path = write_config(
        tmp_path,
        {
            "project": {"name": "system-app"},
            "targets": [
                {"name": "app", "type": "executable", "sources": ["main.c"]}
            ],
            "system": {
                "hostname": "eos-device",
                "image_format": "ext4",
            },
        },
    )

    config = load_config(path)

    assert config.backend == "auto"
    assert config.backend_config == {}
    assert config.system_config == {
        "hostname": "eos-device",
        "image_format": "ext4",
    }


def test_system_section_does_not_override_explicit_backend(tmp_path):
    path = write_config(
        tmp_path,
        {
            "project": {"name": "cmake-system-app"},
            "backend": "cmake",
            "cmake": {"defines": {"BUILD_TESTS": "ON"}},
            "system": {"hostname": "eos-device"},
        },
    )

    config = load_config(path)

    assert config.backend == "cmake"
    assert config.backend_config == {"defines": {"BUILD_TESTS": "ON"}}
    assert config.system_config == {"hostname": "eos-device"}


def test_system_config_must_be_mapping(tmp_path):
    path = write_config(
        tmp_path,
        {"project": {"name": "demo"}, "system": ["invalid"]},
    )

    with pytest.raises(ConfigError, match="'system' must be a mapping"):
        load_config(path)
